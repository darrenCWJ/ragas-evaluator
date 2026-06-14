"""Custom-model routing — registry provider lookup for non-prefix model ids."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services import judge_models
from pipeline.llm import chat_completion

FAKE = {"content": "ok", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class TestRegistryRouting:
    async def test_unknown_model_with_no_registry_entry_rejected(self, tmp_db):
        with pytest.raises(HTTPException) as exc:
            await chat_completion("totally-unknown-model", [{"role": "user", "content": "hi"}])
        assert exc.value.status_code == 400
        assert "Manage Models" in exc.value.detail

    async def test_custom_anthropic_model_routes_to_anthropic(self, tmp_db):
        await judge_models.add_custom_model("my-claude-proxy", "Proxy", "anthropic")
        with patch("pipeline.llm._anthropic_completion", new=AsyncMock(return_value=FAKE)) as mock:
            result = await chat_completion(
                "my-claude-proxy", [{"role": "user", "content": "hi"}]
            )
        assert result["content"] == "ok"
        mock.assert_awaited_once()

    async def test_custom_gateway_model_routes_to_openai_client(self, tmp_db):
        await judge_models.add_custom_model("local-llama-70b", "Llama", "gateway")
        with patch("pipeline.llm._openai_completion", new=AsyncMock(return_value=FAKE)) as mock:
            result = await chat_completion(
                "local-llama-70b", [{"role": "user", "content": "hi"}]
            )
        assert result["content"] == "ok"
        mock.assert_awaited_once()

    async def test_builtin_prefixes_do_not_hit_registry(self, tmp_db):
        # gpt-5.5 style ids route by prefix even without a registry row
        with patch("pipeline.llm._openai_completion", new=AsyncMock(return_value=FAKE)) as mock:
            await chat_completion("gpt-5.5", [{"role": "user", "content": "hi"}])
        mock.assert_awaited_once()
