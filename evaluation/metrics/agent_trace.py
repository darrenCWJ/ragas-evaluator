"""Deterministic agent-trace metrics.

Scores tool usage straight from the recorded agent trace — no LLM cost.
``tool_call_f1`` compares the calls the agent actually made against the
question's ``reference_tool_calls`` metadata.
"""

from __future__ import annotations


def _normalize_reference(ref) -> dict:
    """Accept {"name", "arguments"}, {"name", "args"}, or a bare name string."""
    if isinstance(ref, str):
        return {"name": ref, "arguments": {}}
    if isinstance(ref, dict):
        return {
            "name": ref.get("name", ""),
            "arguments": ref.get("arguments") or ref.get("args") or {},
        }
    return {"name": "", "arguments": {}}


def _call_matches(reference: dict, call: dict) -> bool:
    """A trace call matches when names equal and reference args ⊆ call args."""
    if reference["name"] != call.get("tool", call.get("name", "")):
        return False
    call_args = call.get("arguments") or {}
    return all(str(call_args.get(k)) == str(v) for k, v in reference["arguments"].items())


def tool_call_f1_score(trace_steps: list[dict], reference_tool_calls: list) -> float:
    """F1 between the agent's tool calls and the reference calls.

    Each reference is greedily matched against at most one unmatched trace
    call (same tool name; reference arguments must be a subset of the call's).
    """
    references = [_normalize_reference(r) for r in reference_tool_calls]
    references = [r for r in references if r["name"]]
    calls = list(trace_steps or [])

    if not references and not calls:
        return 1.0
    if not references or not calls:
        return 0.0

    matched = 0
    used: set[int] = set()
    for ref in references:
        for i, call in enumerate(calls):
            if i in used:
                continue
            if _call_matches(ref, call):
                used.add(i)
                matched += 1
                break

    precision = matched / len(calls)
    recall = matched / len(references)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def trace_stats(trace_steps: list[dict]) -> dict:
    """Cheap descriptive stats stored alongside the trace."""
    steps = list(trace_steps or [])
    errors = sum(1 for s in steps if s.get("error"))
    return {
        "agent_steps": len(steps),
        "tool_errors": errors,
        "tool_error_rate": round(errors / len(steps), 4) if steps else 0.0,
    }
