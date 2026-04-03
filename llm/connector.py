"""LLM provider abstraction layer.

Routes chat completion requests to the appropriate provider based on model name.
Currently supports OpenAI models; Glean is stubbed for future implementation.
"""

import logging

from fastapi import HTTPException
from openai import AsyncOpenAI

import openai

logger = logging.getLogger(__name__)

# OpenAI model prefixes — update this tuple when OpenAI releases new model families
OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4")

# Module-level client for connection reuse across calls
_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI()
    return _openai_client


def _is_openai_model(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in OPENAI_PREFIXES)


async def chat_completion(
    model: str,
    messages: list[dict],
    params: dict | None = None,
) -> dict:
    """Dispatch a chat completion request to the appropriate LLM provider.

    Args:
        model: Model identifier (e.g., "gpt-4o-mini", "gpt-4o").
        messages: List of message dicts with "role" and "content" keys.
        params: Optional provider-specific parameters (temperature, top_p, etc.).

    Returns:
        Dict with "content" (str) and "usage" (dict with prompt_tokens, completion_tokens).

    Raises:
        HTTPException: On provider errors or unknown model.
    """
    if _is_openai_model(model):
        return await _openai_completion(model, messages, params)

    if model.startswith("glean"):
        raise HTTPException(status_code=501, detail="Glean provider not yet implemented")

    raise HTTPException(status_code=400, detail=f"Unknown model provider for: {model}")


async def _openai_completion(
    model: str,
    messages: list[dict],
    params: dict | None = None,
) -> dict:
    """Execute a chat completion via OpenAI."""
    client = _get_openai_client()
    extra = params or {}

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            **extra,
        )
    except openai.RateLimitError:
        raise HTTPException(status_code=429, detail="LLM rate limit exceeded")
    except openai.AuthenticationError:
        raise HTTPException(status_code=502, detail="LLM authentication failed")
    except openai.APITimeoutError:
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e.message}")

    content = response.choices[0].message.content
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
    }

    return {"content": content, "usage": usage}


def list_providers() -> list[dict]:
    """Return available LLM providers and their models."""
    return [
        {
            "provider": "openai",
            "status": "available",
            "models": [
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
                {"id": "gpt-4o", "name": "GPT-4o"},
                {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
                {"id": "gpt-4.1-nano", "name": "GPT-4.1 Nano"},
            ],
        },
        {
            "provider": "glean",
            "status": "stub",
            "models": [
                {"id": "glean-agent", "name": "Glean Agent (not yet implemented)"},
            ],
        },
    ]
