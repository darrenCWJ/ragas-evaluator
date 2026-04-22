"""LLM provider abstraction layer.

Routes chat completion requests to the appropriate provider based on model name.
Supports OpenAI, Anthropic (Claude), and Google Gemini.
"""

import logging
import os

from fastapi import HTTPException
from openai import AsyncOpenAI

import openai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gateway mode
# When OPENAI_BASE_URL is set, all models are routed through the OpenAI
# client (which uses the custom base URL). This enables unified gateways
# that expose azure.*, rsn.*, gemini.* etc. via an OpenAI-compatible API.
# ---------------------------------------------------------------------------
_LLM_GATEWAY_MODE = bool(os.environ.get("OPENAI_BASE_URL"))

# ---------------------------------------------------------------------------
# Provider detection (used only when NOT in gateway mode)
# ---------------------------------------------------------------------------
OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4")
ANTHROPIC_PREFIXES = ("claude-",)
GEMINI_PREFIXES = ("gemini-",)

# ---------------------------------------------------------------------------
# Module-level clients (connection reuse)
# ---------------------------------------------------------------------------
_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            max_retries=1,   # 1 retry max — prevent endless loops during gateway outages
            timeout=60.0,    # 60s hard timeout per request
        )
    return _openai_client


async def close_openai_client() -> None:
    """Close module-level OpenAI client. Call during app shutdown."""
    global _openai_client
    if _openai_client is not None:
        await _openai_client.close()
        _openai_client = None


def _is_openai_model(model: str) -> bool:
    return any(model.startswith(p) for p in OPENAI_PREFIXES)


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

async def chat_completion(
    model: str,
    messages: list[dict],
    params: dict | None = None,
) -> dict:
    """Dispatch a chat completion request to the appropriate LLM provider.

    Args:
        model: Model identifier (e.g., "gpt-4o", "claude-sonnet-4-5", "gemini-2.0-flash").
        messages: List of message dicts with "role" and "content" keys.
        params: Optional parameters (temperature, max_tokens, etc.).

    Returns:
        Dict with "content" (str) and "usage" (dict with prompt_tokens, completion_tokens).
    """
    # Gateway mode: all models go through the OpenAI-compatible endpoint
    if _LLM_GATEWAY_MODE:
        return await _openai_completion(model, messages, params)

    if _is_openai_model(model):
        return await _openai_completion(model, messages, params)

    if any(model.startswith(p) for p in ANTHROPIC_PREFIXES):
        return await _anthropic_completion(model, messages, params)

    if any(model.startswith(p) for p in GEMINI_PREFIXES):
        return await _gemini_completion(model, messages, params)

    if model.startswith("glean"):
        raise HTTPException(status_code=501, detail="Glean provider not yet implemented")

    raise HTTPException(status_code=400, detail=f"Unknown model provider for: {model}")


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

async def _openai_completion(
    model: str,
    messages: list[dict],
    params: dict | None = None,
) -> dict:
    client = _get_openai_client()
    extra = params or {}

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            **extra,
        )
    except openai.RateLimitError:
        raise HTTPException(status_code=429, detail="OpenAI rate limit exceeded")
    except openai.AuthenticationError:
        raise HTTPException(status_code=502, detail="OpenAI authentication failed")
    except openai.APITimeoutError:
        raise HTTPException(status_code=504, detail="OpenAI request timed out")
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {e.message}")

    content = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
    }
    return {"content": content, "usage": usage}


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

async def _anthropic_completion(
    model: str,
    messages: list[dict],
    params: dict | None = None,
) -> dict:
    """Execute a chat completion via Anthropic."""
    from config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=502, detail="ANTHROPIC_API_KEY is not configured")

    try:
        import anthropic as _anthropic
    except ImportError:
        raise HTTPException(status_code=502, detail="anthropic package not installed")

    extra = params or {}
    temperature = extra.get("temperature", 0.5)
    max_tokens = extra.get("max_tokens", 1024)

    # Anthropic separates system messages from the conversation
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    conversation = [m for m in messages if m["role"] != "system"]
    system_text = "\n\n".join(system_parts) if system_parts else _anthropic.NOT_GIVEN

    client = _anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_text,
            messages=conversation,
        )
    except _anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Anthropic rate limit exceeded")
    except _anthropic.AuthenticationError:
        raise HTTPException(status_code=502, detail="Anthropic authentication failed — check ANTHROPIC_API_KEY")
    except _anthropic.APITimeoutError:
        raise HTTPException(status_code=504, detail="Anthropic request timed out")
    except _anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {e}")

    content = response.content[0].text if response.content else ""
    usage = {
        "prompt_tokens": response.usage.input_tokens if response.usage else 0,
        "completion_tokens": response.usage.output_tokens if response.usage else 0,
    }
    return {"content": content, "usage": usage}


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

async def _gemini_completion(
    model: str,
    messages: list[dict],
    params: dict | None = None,
) -> dict:
    """Execute a chat completion via Google Gemini."""
    from config import GOOGLE_API_KEY
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=502, detail="GOOGLE_API_KEY is not configured")

    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        raise HTTPException(status_code=502, detail="google-genai package not installed")

    extra = params or {}
    temperature = extra.get("temperature", 0.5)
    max_tokens = extra.get("max_tokens", 1024)

    # Convert OpenAI-style messages to Gemini contents
    # System messages are prepended as user turn; Gemini doesn't have a system role
    role_map = {"user": "user", "assistant": "model", "system": "user"}
    contents = []
    for m in messages:
        gemini_role = role_map.get(m["role"], "user")
        # Merge consecutive same-role messages (Gemini requires alternating turns)
        if contents and contents[-1].role == gemini_role:
            prev_text = contents[-1].parts[0].text
            contents[-1] = genai_types.Content(
                role=gemini_role,
                parts=[genai_types.Part(text=prev_text + "\n\n" + m["content"])],
            )
        else:
            contents.append(
                genai_types.Content(
                    role=gemini_role,
                    parts=[genai_types.Part(text=m["content"])],
                )
            )

    client = genai.Client(api_key=GOOGLE_API_KEY)
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
    except Exception as e:
        err_str = str(e).lower()
        if "quota" in err_str or "rate" in err_str:
            raise HTTPException(status_code=429, detail="Google Gemini rate limit exceeded")
        if "api key" in err_str or "permission" in err_str or "auth" in err_str:
            raise HTTPException(status_code=502, detail="Google Gemini authentication failed — check GOOGLE_API_KEY")
        raise HTTPException(status_code=502, detail=f"Gemini API error: {e}")

    content = response.text or ""
    # Gemini usage metadata
    usage_meta = getattr(response, "usage_metadata", None)
    usage = {
        "prompt_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
        "completion_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
    }
    return {"content": content, "usage": usage}


# ---------------------------------------------------------------------------
# Available judge models + key check
# ---------------------------------------------------------------------------

JUDGE_MODELS = [
    {"id": "gpt-4o",                    "name": "GPT-4o",                     "provider": "openai"},
    {"id": "gpt-4o-mini",               "name": "GPT-4o Mini",                "provider": "openai"},
    {"id": "gpt-4.1",                   "name": "GPT-4.1",                    "provider": "openai"},
    {"id": "gpt-4.1-mini",              "name": "GPT-4.1 Mini",               "provider": "openai"},
    {"id": "claude-opus-4-5",           "name": "Claude Opus 4.5",            "provider": "anthropic"},
    {"id": "claude-sonnet-4-5",         "name": "Claude Sonnet 4.5",          "provider": "anthropic"},
    {"id": "claude-haiku-4-5",          "name": "Claude Haiku 4.5",           "provider": "anthropic"},
    {"id": "gemini-2.0-flash",          "name": "Gemini 2.0 Flash",           "provider": "gemini"},
    {"id": "gemini-1.5-pro",            "name": "Gemini 1.5 Pro",             "provider": "gemini"},
    # Gateway models (available when OPENAI_BASE_URL is set)
    {"id": "azure.claude-haiku-4-5",    "name": "Claude Haiku 4.5 (Azure)",   "provider": "gateway"},
    {"id": "azure.claude-sonnet-4-5",   "name": "Claude Sonnet 4.5 (Azure)",  "provider": "gateway"},
    {"id": "rsn.claude-haiku-4-5",      "name": "Claude Haiku 4.5 (RSN)",     "provider": "gateway"},
    {"id": "rsn.claude-sonnet-4-5",     "name": "Claude Sonnet 4.5 (RSN)",    "provider": "gateway"},
    {"id": "rsn.claude-opus-4-5",       "name": "Claude Opus 4.5 (RSN)",      "provider": "gateway"},
    {"id": "gemini-2.5-flash",          "name": "Gemini 2.5 Flash",           "provider": "gateway"},
    {"id": "gemini-2.5-flash-lite",     "name": "Gemini 2.5 Flash Lite",      "provider": "gateway"},
]


def get_available_judge_models() -> list[dict]:
    """Return all judge models annotated with API key availability."""
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    if _LLM_GATEWAY_MODE:
        # Gateway covers all models with the single OPENAI_API_KEY
        return [{**m, "available": has_openai_key} for m in JUDGE_MODELS]

    availability = {
        "openai":    has_openai_key,
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "gemini":    bool(os.environ.get("GOOGLE_API_KEY")),
        "gateway":   False,  # gateway models unavailable without OPENAI_BASE_URL
    }
    return [{**m, "available": availability[m["provider"]]} for m in JUDGE_MODELS]


def list_providers() -> list[dict]:
    """Return available LLM providers and their models."""
    return [
        {
            "provider": "openai",
            "status": "available",
            "models": [m for m in JUDGE_MODELS if m["provider"] == "openai"],
        },
        {
            "provider": "anthropic",
            "status": "available" if os.environ.get("ANTHROPIC_API_KEY") else "no_key",
            "models": [m for m in JUDGE_MODELS if m["provider"] == "anthropic"],
        },
        {
            "provider": "gemini",
            "status": "available" if os.environ.get("GOOGLE_API_KEY") else "no_key",
            "models": [m for m in JUDGE_MODELS if m["provider"] == "gemini"],
        },
    ]
