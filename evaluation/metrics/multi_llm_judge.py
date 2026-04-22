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
from typing import Optional

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """\
You are an expert evaluator reviewing a chatbot response for accuracy and helpfulness.

QUESTION:
{question}

BOT RESPONSE:
{response}

{context_section}

Your task: Evaluate the response in two steps.

STEP 1 — Reason first. Before producing any output, think through:
- Did the response actually answer the question?
- What did it do well (if anything)?
- What specific parts are inaccurate, unhelpful, missing, or excessive?
- Based on all of the above, what is the overall quality?

STEP 2 — Produce structured output. Using your reasoning, identify 1–4 specific \
claims. A claim is "praise" ONLY if it genuinely helps the user — not just because \
the quote is accurate or honest. A claim is "critique" if the quote is unhelpful, \
missing, misleading, excessive, or fails to answer the question.

If source chunks are provided, reference them when a claim is supported or \
contradicted by a chunk.

Respond with ONLY valid JSON in exactly this format:
{{
  "reasoning": "<2-4 sentences summarising your step 1 analysis>",
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
- reasoning must be written before verdict — let it drive your verdict and claim types
- verdict and claim types must be consistent with your reasoning
- score 1-3: mostly inaccurate or unhelpful
- score 4-6: partially correct but notable issues
- score 7-8: mostly good with minor issues
- score 9-10: accurate, helpful, well-supported
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
    model: str | None = None  # default model when model_assignments is not set
    temperature_min: float = 0.3
    temperature_max: float = 0.75
    model_assignments: list[str] | None = None
    temperature_assignments: list[float] | None = None
    # When model_assignments / temperature_assignments are set:
    #   - len overrides num_evaluators
    #   - evaluator i uses model_assignments[i] and temperature_assignments[i]


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


def _extract_json(text: str) -> dict:
    """Extract the first valid JSON object from text, handles markdown code fences."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    if start == -1:
        return json.loads(text)
    # Walk backwards from the last } to find the shortest valid JSON object.
    # This handles trailing text/null-bytes after the closing brace.
    pos = len(text) - 1
    while pos >= start:
        pos = text.rfind("}", start, pos + 1)
        if pos == -1:
            break
        try:
            return json.loads(text[start : pos + 1])
        except json.JSONDecodeError:
            pos -= 1
    return json.loads(text[start:])


async def _single_evaluator(
    model: str,
    temperature: float,
    evaluator_index: int,
    question: str,
    response: str,
    context_section: str,
) -> dict | None:
    """Run one evaluator call. Returns structured dict or None on failure."""
    from pipeline.llm import chat_completion

    prompt = _JUDGE_PROMPT.format(
        question=question,
        response=response,
        context_section=context_section,
    )
    try:
        result = await chat_completion(
            model,
            [{"role": "user", "content": prompt}],
            {"temperature": temperature, "max_tokens": 800},
        )
        raw = result["content"]
        data = _extract_json(raw)

        reasoning = str(data.get("reasoning", ""))

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
            "reasoning": reasoning,
            "verdict": verdict,
            "score": score,
            "claims": claims,
            "model": model,
        }
    except Exception as e:
        logger.warning("Evaluator %d (model=%s, temp=%.2f) failed: %s", evaluator_index, model, temperature, e, exc_info=True)
        return None


async def run_judge(
    config: MultiLLMJudgeConfig,
    question: str,
    response: str,
    context_dicts: list[dict] | None = None,
) -> list[dict]:
    """Run N evaluators in parallel. Returns list of evaluator result dicts.

    Each result dict: {evaluator_index, verdict, score, claims, model}
    Failed evaluators are omitted from the returned list.
    """
    from config import DEFAULT_EVAL_MODEL

    context_section = _build_context_section(context_dicts or [])

    # Determine models per slot
    if config.model_assignments:
        models = config.model_assignments
        n = len(models)
    else:
        default_model = config.model or DEFAULT_EVAL_MODEL
        n = config.num_evaluators
        models = [default_model] * n

    # Use explicit per-slot temperatures if provided, else linearly space
    if config.temperature_assignments and len(config.temperature_assignments) == n:
        temperatures = config.temperature_assignments
    elif n == 1:
        temperatures = [config.temperature_min]
    else:
        step = (config.temperature_max - config.temperature_min) / (n - 1)
        temperatures = [config.temperature_min + step * i for i in range(n)]

    tasks = [
        _single_evaluator(models[i], temperatures[i], i, question, response, context_section)
        for i in range(n)
    ]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


_VERDICT_SCORES: dict[str, float] = {"positive": 1.0, "mixed": 0.5, "critical": 0.0}


def aggregate_score(evaluations: list[dict], excluded_indices: set[int] | None = None) -> float:
    """Return mean verdict score of non-excluded evaluators (positive=1, mixed=0.5, critical=0).

    excluded_indices: set of evaluator_index values to skip (low reliability).
    """
    excluded = excluded_indices or set()
    active = [e for e in evaluations if e["evaluator_index"] not in excluded]
    if not active:
        active = evaluations
    if not active:
        return 0.0
    scores = [_VERDICT_SCORES.get(e.get("verdict", "mixed"), 0.5) for e in active]
    return round(sum(scores) / len(scores), 4)


# ---------------------------------------------------------------------------
# Criteria Judge — custom-criteria variant of the multi-LLM judge
# ---------------------------------------------------------------------------

_CRITERIA_JUDGE_USER = """\
{criteria_prompt}

---
Evaluate the following chatbot response using the criteria above.

QUESTION:
{question}

BOT RESPONSE:
{response}

{context_section}

Respond with ONLY valid JSON in exactly this format:
{{
  "verdict": "good" | "mixed" | "bad",
  "score": <number>,
  "highlights": [
    {{
      "quote": "<exact substring from the bot response>",
      "type": "supporting" | "contradicting" | "neutral",
      "critique": "<1-2 sentences explaining how this quote relates to the criteria>"
    }}
  ],
  "reasoning": "<1-2 sentence overall justification for the verdict>"
}}

Score mapping: good = 1.0, mixed = 0.5, bad = 0.0
Include 1-4 highlights. Granularity (sentence, phrase, or structural element) should \
match the nature of the criteria as specified in the prompt above.
quote must be a verbatim substring of the bot response.
"""


@dataclass
class CriteriaJudgeConfig:
    metric_name: str
    refined_prompt: str
    num_evaluators: int = 3
    model: str | None = None
    temperature_min: float = 0.3
    temperature_max: float = 0.75
    model_assignments: list[str] | None = None
    temperature_assignments: list[float] | None = None


async def _single_criteria_evaluator(
    model: str,
    temperature: float,
    evaluator_index: int,
    criteria_prompt: str,
    question: str,
    response: str,
    context_section: str,
) -> dict | None:
    """Run one criteria judge evaluator. Returns structured dict or None on failure."""
    from pipeline.llm import chat_completion

    prompt = _CRITERIA_JUDGE_USER.format(
        criteria_prompt=criteria_prompt,
        question=question,
        response=response,
        context_section=context_section,
    )
    try:
        result = await chat_completion(
            model,
            [{"role": "user", "content": prompt}],
            {"temperature": temperature, "max_tokens": 800},
        )
        raw = result["content"]
        data = _extract_json(raw)

        verdict = data.get("verdict", "mixed")
        if verdict not in ("good", "mixed", "bad"):
            verdict = "mixed"

        score_map = {"good": 1.0, "mixed": 0.5, "bad": 0.0}
        score = score_map.get(verdict, 0.5)

        highlights = []
        for h in data.get("highlights", [])[:4]:
            highlights.append({
                "quote": str(h.get("quote", "")),
                "type": h.get("type", "neutral") if h.get("type") in ("supporting", "contradicting", "neutral") else "neutral",
                "critique": str(h.get("critique", "")),
            })

        return {
            "evaluator_index": evaluator_index,
            "verdict": verdict,
            "score": score,
            "highlights": highlights,
            "reasoning": str(data.get("reasoning", "")),
            "model": model,
        }
    except Exception as e:
        logger.warning(
            "Criteria evaluator %d (model=%s, temp=%.2f) failed: %s",
            evaluator_index, model, temperature, e, exc_info=True,
        )
        return None


async def run_criteria_judge(
    config: CriteriaJudgeConfig,
    question: str,
    response: str,
    context_dicts: list[dict] | None = None,
) -> list[dict]:
    """Run N criteria judge evaluators in parallel.

    Returns list of dicts: {evaluator_index, verdict, score, highlights, reasoning, model}
    Failed evaluators are omitted.
    """
    from config import DEFAULT_EVAL_MODEL

    context_section = _build_context_section(context_dicts or [])

    if config.model_assignments:
        models = config.model_assignments
        n = len(models)
    else:
        default_model = config.model or DEFAULT_EVAL_MODEL
        n = config.num_evaluators
        models = [default_model] * n

    if config.temperature_assignments and len(config.temperature_assignments) == n:
        temperatures = config.temperature_assignments
    elif n == 1:
        temperatures = [config.temperature_min]
    else:
        step = (config.temperature_max - config.temperature_min) / (n - 1)
        temperatures = [config.temperature_min + step * i for i in range(n)]

    tasks = [
        _single_criteria_evaluator(
            models[i], temperatures[i], i,
            config.refined_prompt, question, response, context_section,
        )
        for i in range(n)
    ]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def aggregate_criteria_score(
    evaluations: list[dict],
    excluded_indices: set[int] | None = None,
) -> float:
    """Return mean score (0–1) of non-excluded criteria judge evaluators."""
    excluded = excluded_indices or set()
    active = [e for e in evaluations if e["evaluator_index"] not in excluded]
    if not active:
        active = evaluations
    if not active:
        return 0.0
    return round(sum(e["score"] for e in active) / len(active), 4)


# ---------------------------------------------------------------------------
# Reference Judge — compares bot answer against a reference/suggested answer
# ---------------------------------------------------------------------------

_REFERENCE_JUDGE_USER = """\
{criteria_prompt}

---
Compare the following bot response against the suggested/reference answer using the criteria above.

QUESTION:
{question}

SUGGESTED ANSWER (reference):
{reference}

BOT RESPONSE:
{response}

{context_section}

Respond with ONLY valid JSON in exactly this format:
{{
  "verdict": "good" | "mixed" | "bad",
  "score": <number>,
  "highlights": [
    {{
      "quote": "<exact substring from the bot response>",
      "type": "supporting" | "contradicting" | "neutral",
      "critique": "<1-2 sentences explaining how this quote relates to the reference and criteria>"
    }}
  ],
  "reasoning": "<1-2 sentence overall justification comparing the bot response to the reference>"
}}

Score mapping: good = 1.0, mixed = 0.5, bad = 0.0
Include 1-4 highlights. quote must be a verbatim substring of the bot response.
"""


@dataclass
class ReferenceJudgeConfig:
    metric_name: str
    refined_prompt: str
    num_evaluators: int = 3
    model: str | None = None
    temperature_min: float = 0.3
    temperature_max: float = 0.75
    model_assignments: list[str] | None = None
    temperature_assignments: list[float] | None = None


async def _single_reference_evaluator(
    model: str,
    temperature: float,
    evaluator_index: int,
    criteria_prompt: str,
    question: str,
    reference: str,
    response: str,
    context_section: str,
) -> dict | None:
    """Run one reference judge evaluator. Returns structured dict or None on failure."""
    from pipeline.llm import chat_completion

    prompt = _REFERENCE_JUDGE_USER.format(
        criteria_prompt=criteria_prompt,
        question=question,
        reference=reference,
        response=response,
        context_section=context_section,
    )
    try:
        result = await chat_completion(
            model,
            [{"role": "user", "content": prompt}],
            {"temperature": temperature, "max_tokens": 800},
        )
        raw = result["content"]
        data = _extract_json(raw)

        verdict = data.get("verdict", "mixed")
        if verdict not in ("good", "mixed", "bad"):
            verdict = "mixed"

        score_map = {"good": 1.0, "mixed": 0.5, "bad": 0.0}
        score = score_map.get(verdict, 0.5)

        highlights = []
        for h in data.get("highlights", [])[:4]:
            highlights.append({
                "quote": str(h.get("quote", "")),
                "type": h.get("type", "neutral") if h.get("type") in ("supporting", "contradicting", "neutral") else "neutral",
                "critique": str(h.get("critique", "")),
            })

        return {
            "evaluator_index": evaluator_index,
            "verdict": verdict,
            "score": score,
            "highlights": highlights,
            "reasoning": str(data.get("reasoning", "")),
            "model": model,
        }
    except Exception as e:
        logger.warning(
            "Reference evaluator %d (model=%s, temp=%.2f) failed: %s",
            evaluator_index, model, temperature, e, exc_info=True,
        )
        return None


async def run_reference_judge(
    config: ReferenceJudgeConfig,
    question: str,
    reference: str,
    response: str,
    context_dicts: list[dict] | None = None,
) -> list[dict]:
    """Run N reference judge evaluators in parallel.

    Returns list of dicts: {evaluator_index, verdict, score, highlights, reasoning, model}
    Failed evaluators are omitted.
    """
    from config import DEFAULT_EVAL_MODEL

    context_section = _build_context_section(context_dicts or [])

    if config.model_assignments:
        models = config.model_assignments
        n = len(models)
    else:
        default_model = config.model or DEFAULT_EVAL_MODEL
        n = config.num_evaluators
        models = [default_model] * n

    if config.temperature_assignments and len(config.temperature_assignments) == n:
        temperatures = config.temperature_assignments
    elif n == 1:
        temperatures = [config.temperature_min]
    else:
        step = (config.temperature_max - config.temperature_min) / (n - 1)
        temperatures = [config.temperature_min + step * i for i in range(n)]

    tasks = [
        _single_reference_evaluator(
            models[i], temperatures[i], i,
            config.refined_prompt, question, reference, response, context_section,
        )
        for i in range(n)
    ]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]
