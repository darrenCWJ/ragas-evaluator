"""Google Gemini bot connector.

Uses the google-genai SDK to send questions to Gemini models.
"""

from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from pipeline.bot_connectors.base import (
    SOURCE_PROMPT_SUFFIX,
    BotResponse,
)
from config import CONNECTOR_DEFAULT_MODELS
from pipeline.bot_connectors.openai_bot import _parse_inline_citations


class GeminiBotConnector:
    """Bot-under-test connector for Google Gemini models."""

    def __init__(
        self,
        api_key: str,
        model: str = CONNECTOR_DEFAULT_MODELS["gemini"],
        *,
        system_prompt: str = "",
        prompt_for_sources: bool = False,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._system_prompt = system_prompt
        self._prompt_for_sources = prompt_for_sources

    async def query(self, question: str) -> BotResponse:
        system = self._system_prompt
        if self._prompt_for_sources:
            system += SOURCE_PROMPT_SUFFIX

        config = types.GenerateContentConfig(
            system_instruction=system if system else None,
        )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=question,
            config=config,
        )

        content = response.text or ""
        citations = _parse_inline_citations(content) if self._prompt_for_sources else []

        raw: dict[str, Any] = {
            "model_version": response.model_version if hasattr(response, "model_version") else self._model,
        }
        if response.usage_metadata:
            raw["usage"] = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "candidates_tokens": response.usage_metadata.candidates_token_count or 0,
            }

        return BotResponse(answer=content, citations=citations, raw_response=raw)
