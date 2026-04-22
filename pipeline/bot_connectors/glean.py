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
from pipeline.bot_connectors.custom import _validate_endpoint_url

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
        _validate_endpoint_url(base_url)
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
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(_MAX_RETRIES):
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
    """Pull the answer text from Glean's response fragments.

    Handles both standard chat responses (response.fragments) and
    agent responses (messages[] with messageType=CONTENT).
    """
    # 1. Standard chat: response.fragments
    fragments = data.get("response", {}).get("fragments")
    if fragments:
        parts = [f.get("text", "") for f in fragments if f.get("text")]
        if parts:
            return "\n".join(parts)

    # 2. Agent response: find CONTENT message(s)
    messages = data.get("messages", [])
    if messages:
        content_parts = []
        for msg in messages:
            if msg.get("messageType") == "CONTENT":
                for frag in msg.get("fragments", []):
                    text = frag.get("text", "")
                    if text:
                        content_parts.append(text)
        if content_parts:
            return "\n".join(content_parts)

        # Fallback: last message's text fragments
        last_frags = messages[-1].get("fragments", [])
        parts = [f.get("text", "") for f in last_frags if f.get("text")]
        if parts:
            return "\n".join(parts)

    # 3. Fallback: chat_result.answer
    return data.get("chat_result", {}).get("answer", "")


def _extract_citations(data: dict[str, Any]) -> list[Citation]:
    """Extract citations from Glean response.

    Handles multiple response formats:
    1. chat_result.sources (newer standard deployments)
    2. response.fragments with inline citations (standard chat)
    3. messages[].fragments with structuredResults (agent responses)
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

    # 2. Inline fragment citations (standard chat)
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

    # 3. Agent response: structuredResults in messages
    for msg in data.get("messages", []):
        for frag in msg.get("fragments", []):
            for sr in frag.get("structuredResults", []):
                doc = sr.get("document", {})
                # Extract snippet from snippets array or document body
                snippets = sr.get("snippets", [])
                snippet_text = snippets[0].get("snippet", "") if snippets else ""
                # If no snippet, use document title as context
                if not snippet_text:
                    snippet_text = doc.get("title", "")
                citations.append(
                    Citation(
                        title=doc.get("title"),
                        url=doc.get("url"),
                        snippet=snippet_text,
                        datasource=doc.get("datasource"),
                        container=doc.get("container"),
                    )
                )

    # 4. Deduplicate by URL (keep first occurrence)
    seen_urls: set[str | None] = set()
    unique: list[Citation] = []
    for c in citations:
        if c.url in seen_urls and c.url is not None:
            continue
        seen_urls.add(c.url)
        unique.append(c)

    return unique
