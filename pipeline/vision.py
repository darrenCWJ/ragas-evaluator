"""Vision-LLM extraction for image documents.

Sends an uploaded image to a vision-capable model from the already-configured
providers (no OCR dependencies) and returns the extracted text plus a short
description, suitable for chunking and retrieval like any other document.
"""

from __future__ import annotations

import base64
import logging
import os

from fastapi import HTTPException

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = (
    "You are a document digitization assistant. Extract ALL text visible in this "
    "image verbatim, preserving structure (headings, lists, table rows as 'cell | cell'). "
    "After the text, add a line '---' followed by a one-paragraph description of any "
    "non-text content (charts, diagrams, photos) and what it conveys. "
    "If the image contains no text, output only the description after '---'."
)

_DEFAULT_VISION_MODELS = (
    ("OPENAI_API_KEY", "gpt-4o-mini"),
    ("ANTHROPIC_API_KEY", "claude-haiku-4-5"),
    ("GOOGLE_API_KEY", "gemini-2.0-flash"),
)


def pick_vision_model() -> str:
    """Resolve the vision model: explicit config, else first provider with a key."""
    from config import VISION_MODEL

    if VISION_MODEL:
        return VISION_MODEL
    if os.environ.get("OPENAI_BASE_URL"):
        # Gateway mode — gateways route any model name; default to a cheap one.
        return "gpt-4o-mini"
    for env_key, model in _DEFAULT_VISION_MODELS:
        if os.environ.get(env_key):
            return model
    raise HTTPException(
        status_code=422,
        detail=(
            "Image uploads need a vision-capable provider. Configure OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY, or GOOGLE_API_KEY (or set VISION_MODEL explicitly)."
        ),
    )


async def extract_image_text(image_bytes: bytes, mime_type: str) -> str:
    """Extract text + description from an image via the resolved vision model."""
    from pipeline.llm import ANTHROPIC_PREFIXES, GEMINI_PREFIXES

    model = pick_vision_model()
    is_gateway = bool(os.environ.get("OPENAI_BASE_URL"))

    if not is_gateway and any(model.startswith(p) for p in ANTHROPIC_PREFIXES):
        content = await _anthropic_vision(model, image_bytes, mime_type)
    elif not is_gateway and any(model.startswith(p) for p in GEMINI_PREFIXES):
        content = await _gemini_vision(model, image_bytes, mime_type)
    else:
        content = await _openai_vision(model, image_bytes, mime_type)

    if not content.strip():
        raise HTTPException(status_code=422, detail="Vision model returned no content for this image")
    return content


async def _openai_vision(model: str, image_bytes: bytes, mime_type: str) -> str:
    import openai

    from pipeline.llm import _get_openai_client

    b64 = base64.b64encode(image_bytes).decode("ascii")
    client = _get_openai_client()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                ],
            }],
            max_tokens=4000,
            temperature=0.0,
        )
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"Vision extraction failed: {e}") from e
    return response.choices[0].message.content or ""


async def _anthropic_vision(model: str, image_bytes: bytes, mime_type: str) -> str:
    import anthropic as _anthropic

    from pipeline.llm import _get_anthropic_client

    b64 = base64.b64encode(image_bytes).decode("ascii")
    client = _get_anthropic_client()
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4000,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime_type, "data": b64},
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }],
        )
    except _anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Vision extraction failed: {e}") from e
    return response.content[0].text if response.content else ""


async def _gemini_vision(model: str, image_bytes: bytes, mime_type: str) -> str:
    from google.genai import types as genai_types

    from pipeline.llm import _get_gemini_client
    from pipeline.retry import with_backoff

    client = _get_gemini_client()
    try:
        response = await with_backoff(
            lambda: client.aio.models.generate_content(
                model=model,
                contents=[
                    genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    genai_types.Part(text=EXTRACTION_PROMPT),
                ],
                config=genai_types.GenerateContentConfig(temperature=0.0, max_output_tokens=4000),
            ),
            label=f"gemini-vision:{model}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vision extraction failed: {e}") from e
    return response.text or ""
