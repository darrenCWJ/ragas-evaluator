"""Multi-LLM Judge metric.

Runs N independent LLM evaluators (3–6) in parallel, each assessing the bot
response for accuracy and helpfulness. Each evaluator produces structured
claim-level feedback (praise/critique) with quotes linking response text to
source chunks. The aggregate score is the mean of non-excluded evaluator
scores, normalised to 0–1.

Evaluators differ via linearly spaced temperatures (temperature_min →
temperature_max), causing each call to surface different aspects of the
response naturally.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """\
You are an expert evaluator reviewing a chatbot response for accuracy and helpfulness.

QUESTION:
{question}

BOT RESPONSE:
{response}

{context_section}

Your task: Critically review the response. Identify specific claims that are \
accurate/helpful (praise) or inaccurate/misleading/missing (critique). \
Be concrete — quote the exact text from the response you are commenting on.

If source chunks are provided, reference them when a claim is supported or \
contradicted by a chunk.

Respond with ONLY valid JSON in exactly this format:
{{
  "verdict": "positive" | "mixed" | "critical",
  "score": <integer 1-10>,
  "claims": [
    {{
      "type": "praise" | "critique",
      "response_quote": "<exact quote from the bot response>",
      "chunk_reference": "<chunk label e.g. chunk_0> or null",
      "chunk_quote": "<exact quote from that chunk> or null",
      "explanation": "<one or two sentences explaining the claim>"
    }}
  ]
}}

Rules:
- score 1-3: mostly inaccurate or unhelpful
- score 4-6: partially correct but notable issues
- score 7-8: mostly good with minor issues
- score 9-10: accurate, helpful, well-supported
- Include 1–4 claims. Focus on the most impactful points.
- response_quote must be a verbatim substring of the bot response.
- chunk_quote must be a verbatim substring of that chunk (if referenced).
"""

_CONTEXT_SECTION_TEMPLATE = """\
SOURCE CHUNKS (retrieved context used by the bot):
{chunks}
"""


@dataclass
class MultiLLMJudgeConfig:
    num_evaluators: int = 5
    model: str | None = None  # defaults to DEFAULT_EVAL_MODEL at call time
    temperature_min: float = 0.3
    temperature_max: float = 0.75


def _build_context_section(context_dicts: list[dict]) -> str:
    if not context_dicts:
        return ""
    lines = []
    for i, ctx in enumerate(context_dicts[:6]):  # cap at 6 chunks to stay within token limits
        content = ctx.get("content", "").strip()
        if content:
            lines.append(f"[chunk_{i}]\n{content}")
    if not lines:
        return ""
    return _CONTEXT_SECTION_TEMPLATE.format(chunks="\n\n".join(lines))


async def _single_evaluator(
    client: AsyncOpenAI,
    model: str,
    temperature: float,
    evaluator_index: int,
    question: str,
    response: str,
    context_section: str,
) -> dict | None:
    """Run one evaluator call. Returns structured dict or None on failure."""
    prompt = _JUDGE_PROMPT.format(
        question=question,
        response=response,
        context_section=context_section,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(raw)

        # Validate and normalise
        verdict = data.get("verdict", "mixed")
        if verdict not in ("positive", "mixed", "critical"):
            verdict = "mixed"

        score = float(data.get("score", 5))
        score = max(1.0, min(10.0, score))

        claims = []
        for c in data.get("claims", [])[:4]:
            claims.append({
                "type": c.get("type", "critique") if c.get("type") in ("praise", "critique") else "critique",
                "response_quote": str(c.get("response_quote", "")),
                "chunk_reference": c.get("chunk_reference") or None,
                "chunk_quote": c.get("chunk_quote") or None,
                "explanation": str(c.get("explanation", "")),
            })

        return {
            "evaluator_index": evaluator_index,
            "verdict": verdict,
            "score": score,
            "claims": claims,
        }
    except Exception as e:
        logger.warning("Evaluator %d failed (temp=%.2f): %s", evaluator_index, temperature, e)
        return None


async def run_judge(
    config: MultiLLMJudgeConfig,
    question: str,
    response: str,
    context_dicts: list[dict] | None = None,
) -> list[dict]:
    """Run N evaluators in parallel. Returns list of evaluator result dicts.

    Each result dict: {evaluator_index, verdict, score, claims}
    Failed evaluators are omitted from the returned list.
    """
    from config import DEFAULT_EVAL_MODEL

    model = config.model or DEFAULT_EVAL_MODEL
    context_section = _build_context_section(context_dicts or [])
    client = AsyncOpenAI()

    # Linearly space temperatures across evaluators
    n = config.num_evaluators
    if n == 1:
        temperatures = [config.temperature_min]
    else:
        step = (config.temperature_max - config.temperature_min) / (n - 1)
        temperatures = [config.temperature_min + step * i for i in range(n)]

    tasks = [
        _single_evaluator(client, model, temperatures[i], i, question, response, context_section)
        for i in range(n)
    ]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def aggregate_score(evaluations: list[dict], excluded_indices: set[int] | None = None) -> float:
    """Return mean score of non-excluded evaluators, normalised 0–1.

    excluded_indices: set of evaluator_index values to skip (low reliability).
    """
    excluded = excluded_indices or set()
    active = [e for e in evaluations if e["evaluator_index"] not in excluded]
    if not active:
        # Fall back to all evaluators if exclusions remove everything
        active = evaluations
    if not active:
        return 0.0
    mean_score = sum(e["score"] for e in active) / len(active)
    return round((mean_score - 1) / 9, 4)  # normalise 1–10 → 0–1
