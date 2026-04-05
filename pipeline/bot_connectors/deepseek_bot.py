"""DeepSeek bot connector (OpenAI-compatible API).

DeepSeek exposes an OpenAI-compatible chat completions endpoint, so we
reuse the OpenAI SDK with a custom base_url.
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from pipeline.bot_connectors.base import (
    SOURCE_PROMPT_SUFFIX,
    BotResponse,
)
from pipeline.bot_connectors.openai_bot import _parse_inline_citations

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekBotConnector:
    """Bot-under-test connector for DeepSeek models."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        *,
        system_prompt: str = "",
        prompt_for_sources: bool = False,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE_URL)
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
