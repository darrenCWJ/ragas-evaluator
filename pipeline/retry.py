"""Retry with exponential backoff for LLM and HTTP calls.

The OpenAI and Anthropic SDKs already implement exponential backoff that
honors ``Retry-After`` — for those, raising the client ``max_retries`` is
enough. This module covers everything else: the Gemini SDK (no built-in
retry), bot connectors, and whole-operation retries such as metric scoring,
where a transient failure would otherwise null out a result mid-experiment.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# HTTP status codes worth retrying: rate limit + transient upstream failures.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _status_of(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from an exception."""
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _retry_after_of(exc: Exception) -> float | None:
    """Extract a Retry-After hint (seconds) from an exception's response, if any."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return min(float(raw), 120.0) if raw else None
    except (TypeError, ValueError):
        return None


def is_retryable(exc: Exception) -> bool:
    """True for rate limits, transient upstream errors, and network timeouts."""
    status = _status_of(exc)
    if status is not None:
        return status in RETRYABLE_STATUS_CODES
    # Connection/timeout errors without a status code (httpx, asyncio, OS-level)
    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "connect", "network", "transport"))


async def with_backoff[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    label: str = "llm-call",
) -> T:
    """Run ``operation`` retrying transient failures with exponential backoff.

    Non-retryable exceptions (auth failures, validation errors) propagate
    immediately. The final attempt's exception always propagates.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt >= attempts or not is_retryable(exc):
                raise
            last_exc = exc
            delay = _retry_after_of(exc)
            if delay is None:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay *= 0.5 + random.random()  # jitter: 0.5x–1.5x
            logger.warning(
                "%s failed (attempt %d/%d, %s) — retrying in %.1fs",
                label, attempt, attempts, type(exc).__name__, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc if last_exc else RuntimeError(f"{label}: exhausted retries")
