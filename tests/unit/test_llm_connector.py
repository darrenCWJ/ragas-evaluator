"""Unit tests for llm/connector.py."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import openai
from fastapi import HTTPException

from pipeline.llm import (
    chat_completion,
    list_providers,
    _is_openai_model,
    OPENAI_PREFIXES,
)


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the module-level client before each test."""
    import pipeline.llm as mod
    original = mod._openai_client
    mod._openai_client = None
    yield
    mod._openai_client = original


class TestIsOpenaiModel:
    def test_gpt_models(self):
        assert _is_openai_model("gpt-4o") is True
        assert _is_openai_model("gpt-4o-mini") is True
        assert _is_openai_model("gpt-4.1-mini") is True

    def test_o_series(self):
        assert _is_openai_model("o1") is True
        assert _is_openai_model("o3") is True
        assert _is_openai_model("o4-mini") is True

    def test_non_openai(self):
        assert _is_openai_model("claude-3") is False
        assert _is_openai_model("glean-agent") is False
        assert _is_openai_model("llama-3") is False


class TestChatCompletion:
    async def test_openai_model_dispatches(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("pipeline.llm.AsyncOpenAI", return_value=mock_client):
            result = await chat_completion("gpt-4o-mini", [{"role": "user", "content": "Hi"}])

        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 5
        assert result["usage"]["completion_tokens"] == 10

    async def test_unknown_model_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            await chat_completion("unknown-model", [{"role": "user", "content": "Hi"}])
        assert exc_info.value.status_code == 400

    async def test_glean_raises_501(self):
        with pytest.raises(HTTPException) as exc_info:
            await chat_completion("glean-agent", [{"role": "user", "content": "Hi"}])
        assert exc_info.value.status_code == 501

    async def test_rate_limit_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="rate limit", response=MagicMock(status_code=429), body=None
            )
        )
        with patch("pipeline.llm.AsyncOpenAI", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await chat_completion("gpt-4o", [{"role": "user", "content": "Hi"}])
            assert exc_info.value.status_code == 429

    async def test_auth_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.AuthenticationError(
                message="bad key", response=MagicMock(status_code=401), body=None
            )
        )
        with patch("pipeline.llm.AsyncOpenAI", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await chat_completion("gpt-4o", [{"role": "user", "content": "Hi"}])
            assert exc_info.value.status_code == 502

    async def test_timeout_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.APITimeoutError(request=MagicMock())
        )
        with patch("pipeline.llm.AsyncOpenAI", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await chat_completion("gpt-4o", [{"role": "user", "content": "Hi"}])
            assert exc_info.value.status_code == 504

    async def test_params_forwarded(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_response.usage.prompt_tokens = 1
        mock_response.usage.completion_tokens = 1

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("pipeline.llm.AsyncOpenAI", return_value=mock_client):
            await chat_completion("gpt-4o", [{"role": "user", "content": "Hi"}], {"temperature": 0.5})

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("temperature") == 0.5

    async def test_no_usage(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_response.usage = None

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("pipeline.llm.AsyncOpenAI", return_value=mock_client):
            result = await chat_completion("gpt-4o", [{"role": "user", "content": "Hi"}])

        assert result["usage"]["prompt_tokens"] == 0
        assert result["usage"]["completion_tokens"] == 0


class TestListProviders:
    def test_returns_list(self):
        providers = list_providers()
        assert isinstance(providers, list)
        assert len(providers) >= 2

    def test_openai_provider_present(self):
        providers = list_providers()
        names = [p["provider"] for p in providers]
        assert "openai" in names

    def test_provider_structure(self):
        for p in list_providers():
            assert "provider" in p
            assert "status" in p
            assert "models" in p
            assert isinstance(p["models"], list)
