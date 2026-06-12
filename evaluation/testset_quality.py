"""Test set quality audit — find bad test questions before they mislead users.

A test set is the measuring stick for the user's agent; a flawed question
produces a flawed verdict. This module audits every question (generated OR
uploaded) and attaches a quality assessment to its metadata so the UI can
flag, filter, and explain.

Deterministic checks (free):
    too_short        — question under 12 characters
    no_reference     — empty reference answer
    verbatim_leakage — the question copies a long span of its source context
                       verbatim (the agent can pattern-match instead of
                       understanding; inflates scores)
    no_contexts      — grounded question types with no reference contexts

LLM checks (one call per question, skipped for refusal-tagged questions):
    ungrounded       — the reference answer is NOT supported by the
                       reference contexts (the "gold" answer is itself wrong)
    not_self_contained — the question can't be understood without seeing the
                       source document ("What does section 3.2 say?")
    trivial          — answerable by copying a single sentence verbatim
"""

import asyncio
import json
import logging

from config import DEFAULT_EVAL_MODEL
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

_AUDIT_CONCURRENCY = 8
_MIN_QUESTION_CHARS = 12
_LEAKAGE_NGRAM = 8  # consecutive words shared with a context to count as leakage

# Question types that are grounded in retrieved contexts. Out-of-KB questions
# legitimately have none.
_GROUNDED_TYPES = {
    "single_hop_specific_query_synthesizer",
    "multi_hop_abstract_query_synthesizer",
    "multi_hop_specific_query_synthesizer",
}

_LLM_AUDIT_PROMPT = """You are auditing the quality of a QA test case used to evaluate an AI assistant.

QUESTION:
{question}

REFERENCE ANSWER (the "gold" answer the assistant is graded against):
{reference}

SOURCE CONTEXTS (what the reference answer should be based on; may be empty):
{contexts}

Evaluate three things:
1. grounded — is the reference answer fully supported by the source contexts? (If contexts are empty, judge whether the reference answer makes unverifiable factual claims.)
2. self_contained — can the question be understood and answered without having the source document in front of you? (Questions like "What does the table above show?" or "What is mentioned in section 3.2?" are NOT self-contained.)
3. non_trivial — does answering require at least minimal comprehension, rather than copying one sentence verbatim from the context?

Return ONLY JSON:
{{"grounded": true/false, "self_contained": true/false, "non_trivial": true/false, "reasoning": "<one sentence on the worst problem, or 'ok'>"}}
"""


def deterministic_checks(question: str, reference_answer: str, contexts: list[str], question_type: str = "") -> list[str]:
    """Return flag names for mechanically detectable quality problems."""
    flags: list[str] = []
    q = (question or "").strip()
    if len(q) < _MIN_QUESTION_CHARS:
        flags.append("too_short")
    if not (reference_answer or "").strip():
        flags.append("no_reference")
    if question_type in _GROUNDED_TYPES and not contexts:
        flags.append("no_contexts")
    if contexts and _has_verbatim_leakage(q, contexts):
        flags.append("verbatim_leakage")
    return flags


def _has_verbatim_leakage(question: str, contexts: list[str]) -> bool:
    """True when the question shares a long consecutive word run with a context."""
    q_words = question.lower().split()
    if len(q_words) < _LEAKAGE_NGRAM:
        return False
    q_grams = {
        " ".join(q_words[i : i + _LEAKAGE_NGRAM])
        for i in range(len(q_words) - _LEAKAGE_NGRAM + 1)
    }
    for ctx in contexts:
        text = (ctx if isinstance(ctx, str) else ctx.get("content", "")).lower()
        collapsed = " ".join(text.split())
        if any(gram in collapsed for gram in q_grams):
            return True
    return False


async def _llm_audit(question: str, reference_answer: str, contexts: list[str]) -> dict:
    """Run the LLM grounding/self-containment/triviality audit."""
    ctx_text = "\n---\n".join(
        (c if isinstance(c, str) else c.get("content", ""))[:4000] for c in contexts[:6]
    ) or "(none)"

    async def _call():
        return await chat_completion(
            DEFAULT_EVAL_MODEL,
            [{"role": "user", "content": _LLM_AUDIT_PROMPT.format(
                question=question[:2000],
                reference=reference_answer[:4000],
                contexts=ctx_text,
            )}],
            {"temperature": 0.0, "max_tokens": 300},
        )

    result = await with_backoff(_call, attempts=3, label="testset-audit")
    text = result["content"]
    data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    flags = []
    if data.get("grounded") is False:
        flags.append("ungrounded")
    if data.get("self_contained") is False:
        flags.append("not_self_contained")
    if data.get("non_trivial") is False:
        flags.append("trivial")
    return {"flags": flags, "reasoning": str(data.get("reasoning", ""))[:300]}


async def audit_question(q_row: dict, *, use_llm: bool = True) -> dict:
    """Audit one question. Returns {"score", "flags", "reasoning"}.

    Score: 1.0 minus 0.25 per flag, floored at 0. Refusal-tagged questions
    skip grounding checks (they have no contexts by design).
    """
    question = q_row.get("question", "")
    reference = q_row.get("reference_answer", "")
    contexts = q_row.get("reference_contexts") or []
    metadata = q_row.get("metadata") or {}
    is_refusal = metadata.get("expected_behavior") == "refusal"

    flags = deterministic_checks(question, reference, contexts, q_row.get("question_type", ""))
    if is_refusal:
        flags = [f for f in flags if f not in ("no_contexts",)]
    reasoning = ""

    if use_llm and not is_refusal:
        try:
            llm_result = await _llm_audit(question, reference, contexts)
            flags.extend(llm_result["flags"])
            reasoning = llm_result["reasoning"]
        except Exception as exc:
            logger.warning("LLM audit failed for question %s: %s", q_row.get("id"), exc)
            reasoning = f"LLM audit unavailable: {exc}"

    score = max(0.0, 1.0 - 0.25 * len(flags))
    return {"score": round(score, 2), "flags": flags, "reasoning": reasoning}


async def audit_test_set(questions: list[dict], *, use_llm: bool = True) -> list[tuple[int, dict]]:
    """Audit all questions concurrently. Returns [(question_id, assessment)]."""
    semaphore = asyncio.Semaphore(_AUDIT_CONCURRENCY)

    async def _one(q: dict) -> tuple[int, dict]:
        async with semaphore:
            return q["id"], await audit_question(q, use_llm=use_llm)

    return list(await asyncio.gather(*[_one(q) for q in questions]))


def summarize_audit(assessments: list[tuple[int, dict]]) -> dict:
    """Aggregate an audit run into the summary the UI shows."""
    if not assessments:
        return {"audited": 0, "avg_score": None, "flag_counts": {}, "flagged_question_ids": []}
    flag_counts: dict[str, int] = {}
    flagged_ids: list[int] = []
    total = 0.0
    for qid, a in assessments:
        total += a["score"]
        if a["flags"]:
            flagged_ids.append(qid)
        for f in a["flags"]:
            flag_counts[f] = flag_counts.get(f, 0) + 1
    return {
        "audited": len(assessments),
        "avg_score": round(total / len(assessments), 3),
        "flag_counts": dict(sorted(flag_counts.items(), key=lambda kv: -kv[1])),
        "flagged_question_ids": flagged_ids,
    }
