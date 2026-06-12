"""Conversation retention — does the final answer honor the earlier turns?

Runs only on multi-turn test questions (``metadata.turns`` present) whose
runtime transcript was captured (``metadata._transcript``, injected by the
experiment runner for bot runs). Judges whether the final answer correctly
uses and stays consistent with information established earlier in the
conversation — the failure mode single-turn metrics cannot see.

Scores: 1.0 retained · 0.5 partial (ignores some established context but no
contradiction) · 0.0 contradicts or forgets the earlier turns.
"""

import json
import logging

from config import DEFAULT_EVAL_MODEL
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are auditing a multi-turn conversation with an AI assistant.

CONVERSATION (earlier turns):
{transcript}

FINAL USER QUESTION:
{question}

ASSISTANT'S FINAL ANSWER:
{answer}

Judge whether the final answer correctly RETAINS the earlier conversation:
- "retained": uses and stays consistent with the facts, constraints, and corrections established in earlier turns
- "partial": ignores some established context, but does not contradict it
- "forgot": contradicts earlier turns, re-asks for information already given, or answers as if the earlier turns never happened

Return ONLY JSON: {{"verdict": "retained" | "partial" | "forgot", "reasoning": "<one sentence citing the turn it relates to>"}}
"""

_VERDICT_SCORES = {"retained": 1.0, "partial": 0.5, "forgot": 0.0}


def create_scorer(llm):
    # Judge uses chat_completion directly; llm handle kept for registry uniformity.
    return llm


def _format_transcript(transcript: list[dict]) -> str:
    lines = []
    for turn in transcript:
        speaker = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{speaker}: {str(turn.get('content', ''))[:1500]}")
    return "\n".join(lines)


async def score(scorer, question: str, answer: str, metadata: dict | None) -> float | None:
    """Score conversation retention; None for single-turn questions."""
    transcript = (metadata or {}).get("_transcript") or []
    if not transcript:
        return None
    if not (answer or "").strip():
        return 0.0

    async def _call():
        return await chat_completion(
            DEFAULT_EVAL_MODEL,
            [{"role": "user", "content": _JUDGE_PROMPT.format(
                transcript=_format_transcript(transcript)[:12000],
                question=question[:2000],
                answer=answer[:8000],
            )}],
            {"temperature": 0.0, "max_tokens": 300},
        )

    result = await with_backoff(_call, attempts=3, label="conversation-retention-judge")
    text = result["content"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        verdict = str(data.get("verdict", "")).lower()
    except (ValueError, TypeError):
        logger.warning("conversation_retention: unparseable judge reply: %s", text[:200])
        return None
    return _VERDICT_SCORES.get(verdict)
