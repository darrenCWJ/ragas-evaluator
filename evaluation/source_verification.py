"""Source verification: checks whether bot-cited URLs are reachable and support the answer.

Statuses:
- "verified"     — URL reachable, content supports the claim
- "hallucinated" — URL unreachable (404/DNS) or content contradicts the claim
- "inaccessible" — URL returns 401/403/auth wall; cannot verify
- "unverifiable" — No URL provided for the citation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from pipeline.llm import chat_completion

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = 15  # seconds
_MAX_CONTENT_LENGTH = 8000  # chars sent to LLM for verification

_VERIFY_SYSTEM_PROMPT = (
    "You are a fact-checking assistant. You will be given a CLAIM and a SOURCE TEXT. "
    "Determine whether the source text supports the claim. "
    "Reply with exactly one word: SUPPORTS or CONTRADICTS."
)


@dataclass(frozen=True)
class VerificationResult:
    citation_index: int
    title: str | None
    url: str | None
    status: str
    details: str | None


async def verify_citation(
    citation: dict[str, Any],
    citation_index: int,
    answer: str,
    llm_model: str = "gpt-4o-mini",
) -> VerificationResult:
    """Verify a single citation against the bot's answer.

    Args:
        citation: Dict with optional keys: title, url, snippet.
        citation_index: Position of this citation in the citations list.
        answer: The bot's full answer text (used as the claim for verification).
        llm_model: Model to use for content-vs-claim checking.
    """
    title = citation.get("title")
    url = citation.get("url")

    if not url:
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="unverifiable",
            details="No URL provided",
        )

    # Attempt to fetch the URL
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=_FETCH_TIMEOUT
        ) as client:
            response = await client.get(url, headers={"User-Agent": "RagasEval/1.0"})
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="hallucinated",
            details="Connection failed or timed out",
        )
    except Exception as exc:
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="hallucinated",
            details=f"Request error: {type(exc).__name__}",
        )

    status_code = response.status_code

    if status_code == 404:
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="hallucinated",
            details="URL returned 404 Not Found",
        )

    if status_code in (401, 403):
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="inaccessible",
            details=f"URL returned {status_code}",
        )

    if status_code >= 400:
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="hallucinated",
            details=f"URL returned HTTP {status_code}",
        )

    # URL is reachable (2xx/3xx) — check content supports the answer
    content_text = response.text[:_MAX_CONTENT_LENGTH]
    if not content_text.strip():
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="unverifiable",
            details="Page returned empty content",
        )

    try:
        llm_result = await chat_completion(
            model=llm_model,
            messages=[
                {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"CLAIM:\n{answer[:2000]}\n\n"
                        f"SOURCE TEXT:\n{content_text}"
                    ),
                },
            ],
            params={"temperature": 0, "max_tokens": 10},
        )
        verdict = llm_result["content"].strip().upper()
    except Exception as exc:
        logger.warning("LLM verification failed for %s: %s", url, exc)
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="unverifiable",
            details=f"LLM verification error: {type(exc).__name__}",
        )

    if "SUPPORTS" in verdict:
        return VerificationResult(
            citation_index=citation_index,
            title=title,
            url=url,
            status="verified",
            details="Content supports the claim",
        )

    return VerificationResult(
        citation_index=citation_index,
        title=title,
        url=url,
        status="hallucinated",
        details="Content does not support the claim",
    )


async def verify_all_citations(
    citations: list[dict[str, Any]],
    answer: str,
    llm_model: str = "gpt-4o-mini",
) -> list[VerificationResult]:
    """Verify all citations for a single bot response.

    Runs sequentially to be respectful of rate limits and target URLs.
    """
    results: list[VerificationResult] = []
    for idx, citation in enumerate(citations):
        result = await verify_citation(citation, idx, answer, llm_model)
        results.append(result)
    return results
