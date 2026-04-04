"""Glean chat API bot connector.

Sends questions to Glean's /rest/api/v1/chat endpoint and extracts
the answer text plus any inline citations.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from pipeline.bot_connectors.base import BotResponse, Citation

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0


class GleanBotConnector:
    """Connector for the Glean conversational search API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://company-be.glean.com",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def query(self, question: str) -> BotResponse:
        body: dict[str, Any] = {
            "messages": [
                {"fragments": [{"text": question}]}
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/rest/api/v1/chat",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()

        data = resp.json()

        answer = _extract_answer(data)
        citations = _extract_citations(data)

        return BotResponse(answer=answer, citations=citations, raw_response=data)


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
            )
        )

    return citations
