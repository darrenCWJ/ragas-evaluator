"""OpenAI chat completions bot connector.

Uses the OpenAI SDK to send questions and collect answers.  When
``prompt_for_sources`` is enabled, the system prompt asks the model to
cite sources; we then parse numbered references from the response text.
"""

from __future__ import annotations

import re
from typing import Any

from openai import AsyncOpenAI

from config import CONNECTOR_DEFAULT_MODELS
from pipeline.bot_connectors.base import (
    SOURCE_PROMPT_SUFFIX,
    BotResponse,
    Citation,
)


class OpenAIBotConnector:
    """Bot-under-test connector for OpenAI models."""

    def __init__(
        self,
        api_key: str,
        model: str = CONNECTOR_DEFAULT_MODELS["openai"],
        *,
        system_prompt: str = "",
        prompt_for_sources: bool = False,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=1, timeout=120.0)
        self._model = model
        self._system_prompt = system_prompt
        self._prompt_for_sources = prompt_for_sources

    async def query(self, question: str) -> BotResponse:
        system = self._system_prompt
        if self._prompt_for_sources:
            system += SOURCE_PROMPT_SUFFIX

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": question})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )

        content = response.choices[0].message.content or ""
        citations = _parse_inline_citations(content) if self._prompt_for_sources else []

        raw: dict[str, Any] = {
            "id": response.id,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }

        return BotResponse(answer=content, citations=citations, raw_response=raw)


# ---------------------------------------------------------------------------
# Citation parsing helpers
# ---------------------------------------------------------------------------

_REF_LINE_RE = re.compile(
    r"^\[(\d+)\]\s*(.+?)(?:\s*[-–—]\s*(https?://\S+))?\s*$",
    re.MULTILINE,
)


def _parse_inline_citations(text: str) -> list[Citation]:
    """Parse ``[n] Title - URL`` references from the tail of a response."""
    return [
        Citation(
            title=m.group(2).strip() or None,
            url=m.group(3) or None,
            snippet=None,
        )
        for m in _REF_LINE_RE.finditer(text)
    ]
