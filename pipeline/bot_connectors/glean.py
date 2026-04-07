"""Glean chat API bot connector.

Sends questions to Glean's /rest/api/v1/chat endpoint and extracts
the answer text plus any inline citations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from pipeline.bot_connectors.base import BotResponse, Citation

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 2.0  # seconds


class GleanBotConnector:
    """Connector for the Glean conversational search API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://company-be.glean.com",
        agent_id: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._timeout = timeout

    async def query(self, question: str) -> BotResponse:
        body: dict[str, Any] = {
            "messages": [
                {"fragments": [{"text": question}]}
            ],
        }
        if self._agent_id:
            body["agentId"] = self._agent_id
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        data = await self._post_with_retry(body, headers)

        answer = _extract_answer(data)
        citations = _extract_citations(data)

        return BotResponse(answer=answer, citations=citations, raw_response=data)

    async def _post_with_retry(
        self, body: dict, headers: dict
    ) -> dict[str, Any]:
        """POST to Glean with exponential backoff on 429 and 5xx errors."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/rest/api/v1/chat",
                    json=body,
                    headers=headers,
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == _MAX_RETRIES - 1:
                    logger.error(
                        "Glean %d after %d attempts. Body: %s",
                        resp.status_code,
                        _MAX_RETRIES,
                        resp.text[:500],
                    )
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else backoff
                logger.info(
                    "Glean %d, retrying in %.1fs (attempt %d/%d)",
                    resp.status_code, wait, attempt + 1, _MAX_RETRIES,
                )
                await asyncio.sleep(wait)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        # Unreachable, but satisfies type checker
        raise RuntimeError("Exhausted retries")


def _extract_answer(data: dict[str, Any]) -> str:
    """Pull the answer text from Glean's response fragments."""
    fragments = (
        data.get("response", {}).get("fragments")
        or data.get("messages", [{}])[-1:][0].get("fragments")
        or []
    )
    parts = [f.get("text", "") for f in fragments if f.get("text")]
    if parts:
        return "\n".join(parts)

    # Fallback: some Glean deployments nest under chat_result
    return data.get("chat_result", {}).get("answer", "")


def _extract_citations(data: dict[str, Any]) -> list[Citation]:
    """Extract citations from Glean response.

    Glean can return sources in several locations depending on the
    deployment version; we check the most common ones.
    """
    citations: list[Citation] = []

    # 1. chat_result.sources (common in newer deployments)
    for src in data.get("chat_result", {}).get("sources", []):
        citations.append(
            Citation(
                title=src.get("title"),
                url=src.get("url"),
                snippet=src.get("snippet"),
                datasource=src.get("datasource"),
                container=src.get("container"),
            )
        )

    # 2. Inline fragment citations
    fragments = data.get("response", {}).get("fragments", [])
    for frag in fragments:
        cit = frag.get("citation")
        if cit is None:
            continue
        source_doc = cit.get("sourceDocument", {})
        citations.append(
            Citation(
                title=source_doc.get("title"),
                url=source_doc.get("url"),
                snippet=frag.get("text"),
                datasource=source_doc.get("datasource"),
                container=source_doc.get("container"),
            )
        )

    # 3. Deduplicate by URL (keep first occurrence)
    seen_urls: set[str | None] = set()
    unique: list[Citation] = []
    for c in citations:
        if c.url in seen_urls and c.url is not None:
            continue
        seen_urls.add(c.url)
        unique.append(c)

    return unique
