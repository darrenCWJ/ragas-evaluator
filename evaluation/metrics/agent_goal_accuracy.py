"""Agent goal accuracy — did the agent actually achieve the user's goal?

LLM-judged binary metric for agent experiments: given the user's request
(the goal), the agent's final answer, a summary of the tool actions it took,
and the reference answer (the desired outcome), the judge decides whether
the goal was achieved.

(Replaces an unwired ragas AgentGoalAccuracy stub — ragas' version needs
multi-turn conversation objects; this adaptation judges straight from the
app's single-turn agent traces.)
"""

from __future__ import annotations

import json
import logging

from config import DEFAULT_EVAL_MODEL
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

_MAX_TRACE_ACTIONS = 20

_JUDGE_PROMPT = """You are evaluating whether an AI agent achieved the user's goal.

USER'S GOAL (their request):
{question}

ACTIONS THE AGENT TOOK (tool calls, in order):
{actions}

AGENT'S FINAL ANSWER:
{answer}

DESIRED OUTCOME (reference):
{reference}

Did the agent achieve the user's goal, judged by the final answer and the
actions taken against the desired outcome? Partial or wrong outcomes count
as not achieved.

Return ONLY a JSON object: {{"achieved": true|false, "reasoning": "<one sentence>"}}"""


def _format_actions(trace_steps: list[dict]) -> str:
    if not trace_steps:
        return "(no tool calls)"
    lines = []
    for step in trace_steps[:_MAX_TRACE_ACTIONS]:
        name = step.get("tool", step.get("name", "?"))
        args = json.dumps(step.get("arguments") or {})[:200]
        status = "ERROR" if step.get("error") else "ok"
        lines.append(f"- {name}({args}) → {status}")
    if len(trace_steps) > _MAX_TRACE_ACTIONS:
        lines.append(f"... and {len(trace_steps) - _MAX_TRACE_ACTIONS} more")
    return "\n".join(lines)


async def agent_goal_accuracy_score(
    question: str,
    answer: str,
    reference: str,
    trace_steps: list[dict],
    judge_model: str | None = None,
) -> float:
    """1.0 when the judge deems the goal achieved, else 0.0."""
    prompt = _JUDGE_PROMPT.format(
        question=question[:4000],
        actions=_format_actions(trace_steps),
        answer=(answer or "")[:6000],
        reference=(reference or "")[:4000],
    )

    async def _call():
        return await chat_completion(
            judge_model or DEFAULT_EVAL_MODEL,
            [{"role": "user", "content": prompt}],
            {"temperature": 0.0, "max_tokens": 300},
        )

    result = await with_backoff(_call, attempts=3, label="agent-goal-accuracy")
    content = result["content"].strip()
    try:
        start = content.find("{")
        end = content.rfind("}")
        data = json.loads(content[start : end + 1])
        return 1.0 if data.get("achieved") else 0.0
    except (ValueError, AttributeError):
        logger.warning("agent_goal_accuracy: unparseable judge reply: %.200s", content)
        # Unparseable verdict — be conservative and count as not achieved.
        return 0.0
