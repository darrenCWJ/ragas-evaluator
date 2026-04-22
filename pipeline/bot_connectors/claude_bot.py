"""Anthropic Claude bot connector.

Uses the Anthropic SDK to send questions to Claude models and collect
answers.  Source prompting and citation parsing follow the same pattern
as the OpenAI connector.
"""

from __future__ import annotations

from typing import Any

import anthropic

from pipeline.bot_connectors.base import (
    SOURCE_PROMPT_SUFFIX,
    BotResponse,
)
from config import CONNECTOR_DEFAULT_MODELS
from pipeline.bot_connectors.openai_bot import _parse_inline_citations


class ClaudeBotConnector:
    """Bot-under-test connector for Anthropic Claude models."""

    def __init__(
        self,
        api_key: str,
        model: str = CONNECTOR_DEFAULT_MODELS["claude"],
        *,
        system_prompt: str = "",
        prompt_for_sources: bool = False,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=1, timeout=120.0)
        self._model = model
        self._system_prompt = system_prompt
        self._prompt_for_sources = prompt_for_sources

    async def query(self, question: str) -> BotResponse:
        system = self._system_prompt
        if self._prompt_for_sources:
            system += SOURCE_PROMPT_SUFFIX

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": question}],
        }
        if system:
            kwargs["system"] = system

        response = await self._client.messages.create(**kwargs)

        content = "".join(
            block.text for block in response.content if block.type == "text"
        )
        citations = _parse_inline_citations(content) if self._prompt_for_sources else []

        raw: dict[str, Any] = {
            "id": response.id,
            "model": response.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

        return BotResponse(answer=content, citations=citations, raw_response=raw)
