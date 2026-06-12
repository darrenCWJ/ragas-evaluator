"""Agentic tool-calling loop.

Drives a model through repeated chat_completion calls: when the model requests
tool calls, they are executed via the supplied executor and the results are
fed back until the model produces a final text answer (or a step/budget limit
is hit). The full step trace is returned for storage and scoring.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from pipeline.llm import chat_completion

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 8

# An executor resolves one tool call to its string result.
ToolExecutor = Callable[[str, dict], Awaitable[str]]


async def run_agent(
    model: str,
    messages: list[dict],
    tools: list[dict],
    executor: ToolExecutor,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    params: dict | None = None,
) -> dict:
    """Run the tool-calling loop until the model answers or limits are hit.

    Args:
        model: Model identifier routed via pipeline.llm.chat_completion.
        messages: Initial canonical messages (system/user turns).
        tools: Tool specs ``[{"name", "description", "parameters"}]``.
        executor: Async fn(name, arguments) -> result string. Exceptions are
            captured and fed back to the model as an error result.
        max_steps: Maximum LLM round-trips before forcing an answer.
        params: Extra completion params (temperature, max_tokens…).

    Returns:
        ``{"answer": str, "steps": [...], "turns": [...], "usage": {...},
        "stop_reason": str}`` where each step is ``{"tool", "arguments",
        "result", "latency_ms", "error", "turn"}`` and each turn is one LLM
        round that requested tools: ``{"thought": <assistant text narrated
        alongside the tool calls>, "tool_calls": [names], "latency_ms",
        "steps": [...]}`` — the model's visible reasoning between actions.
    """
    conversation = list(messages)
    steps: list[dict] = []
    turns: list[dict] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    stop_reason = "max_steps"
    answer = ""

    for _ in range(max_steps):
        llm_started = time.monotonic()
        response = await chat_completion(model, conversation, params, tools=tools)
        llm_latency_ms = int((time.monotonic() - llm_started) * 1000)
        usage = response.get("usage") or {}
        total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        total_usage["completion_tokens"] += usage.get("completion_tokens", 0)

        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            answer = response.get("content", "")
            stop_reason = "answer"
            break

        turn = {
            "thought": (response.get("content") or "").strip(),
            "tool_calls": [tc["name"] for tc in tool_calls],
            "latency_ms": llm_latency_ms,
            "steps": [],
        }
        turns.append(turn)

        conversation.append({
            "role": "assistant",
            "content": response.get("content") or None,
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            started = time.monotonic()
            error: str | None = None
            try:
                result = await executor(tc["name"], tc["arguments"])
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tc["name"], exc)
                error = str(exc)
                result = f"Error: {exc}"
            latency_ms = int((time.monotonic() - started) * 1000)
            step = {
                "tool": tc["name"],
                "arguments": tc["arguments"],
                "result": result[:4000],
                "latency_ms": latency_ms,
                "error": error,
                "turn": len(turns),
            }
            steps.append(step)
            turn["steps"].append(step)
            conversation.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "content": result[:8000],
            })
    else:
        # Step budget exhausted mid-tool-use: ask for a final answer without tools.
        conversation.append({
            "role": "user",
            "content": "Tool budget exhausted. Answer now using the information you already have.",
        })
        response = await chat_completion(model, conversation, params)
        usage = response.get("usage") or {}
        total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
        answer = response.get("content", "")

    return {
        "answer": answer,
        "steps": steps,
        "turns": turns,
        "usage": total_usage,
        "stop_reason": stop_reason,
    }
