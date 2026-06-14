"""Topic adherence — does the answer stay within the question's allowed topics?

LLM-judged metric gated on the ``topics`` list in question metadata (set per
question at upload/generation time). The judge checks whether the response
keeps to those topics and refuses or redirects content outside them.
Score = 1.0 fully adherent, 0.5 partially off-topic, 0.0 off-topic.

(Replaces an unwired ragas TopicAdherence stub — ragas' version needs
multi-turn conversation objects this app's single-turn rows don't have.)
"""

from __future__ import annotations

import json
import logging

from config import DEFAULT_EVAL_MODEL
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are evaluating whether an AI assistant's answer stays within its ALLOWED TOPICS.

ALLOWED TOPICS:
{topics}

USER'S QUESTION:
{question}

ASSISTANT'S ANSWER:
{answer}

Judge the ANSWER only (the question may try to lead it off-topic):
- "adherent": everything in the answer falls within the allowed topics, or it
  appropriately declines off-topic parts.
- "partial": a meaningful portion of the answer drifts outside the topics.
- "off_topic": the answer substantially addresses content outside the topics.

Return ONLY a JSON object: {{"verdict": "adherent"|"partial"|"off_topic", "reasoning": "<one sentence>"}}"""

_VERDICT_SCORES = {"adherent": 1.0, "partial": 0.5, "off_topic": 0.0}


async def topic_adherence_score(
    question: str,
    answer: str,
    topics: list[str],
    judge_model: str | None = None,
) -> float:
    topics_text = "\n".join(f"- {str(t)[:200]}" for t in topics[:25]) or "(none)"
    prompt = _JUDGE_PROMPT.format(
        topics=topics_text,
        question=question[:4000],
        answer=(answer or "")[:6000],
    )

    async def _call():
        return await chat_completion(
            judge_model or DEFAULT_EVAL_MODEL,
            [{"role": "user", "content": prompt}],
            {"temperature": 0.0, "max_tokens": 300},
        )

    result = await with_backoff(_call, attempts=3, label="topic-adherence")
    content = result["content"].strip()
    try:
        start = content.find("{")
        end = content.rfind("}")
        data = json.loads(content[start : end + 1])
        return _VERDICT_SCORES.get(str(data.get("verdict", "")).lower(), 0.0)
    except (ValueError, AttributeError):
        logger.warning("topic_adherence: unparseable judge reply: %.200s", content)
        return 0.0
