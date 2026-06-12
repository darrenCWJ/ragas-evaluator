"""Skill adherence scoring — judge a response against a directive checklist.

Two layers:
- ``check_format_rules``  — deterministic checks for machine-checkable format
  directives (JSON validity, bullet/heading presence, word caps). Free and
  exact where they apply.
- ``judge_adherence``     — LLM judge scoring every directive with per-directive
  pass/fail + reasoning. Baseline (no-skill) responses are judged against the
  same checklist so the skill's lift is measurable.
"""

import json
import logging
import re

from config import DEFAULT_EVAL_MODEL
from evaluation.skills.parser import _extract_json_object
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are auditing whether an AI response follows a set of directives it was given.

DIRECTIVES:
{directives}

USER QUESTION:
{question}

AI RESPONSE:
{response}

For EVERY directive, judge whether this response complies. Judge only what is observable in the response — a directive about behavior not exercised by this question (e.g. "when asked about pricing, ..." for a non-pricing question) is "not_applicable".

Return ONLY a JSON object:
{{
  "results": [
    {{"id": "<directive id>", "verdict": "pass" | "fail" | "not_applicable", "reasoning": "<one sentence>"}}
  ]
}}
"""


def check_format_rules(response: str, directives: list[dict]) -> dict[str, bool | None]:
    """Deterministic checks for machine-checkable format directives.

    Returns {directive_id: True/False} for rules we can verify mechanically,
    omitting directives we can't. The LLM judge still covers everything.
    """
    results: dict[str, bool | None] = {}
    for d in directives:
        if not d.get("machine_checkable") or d.get("kind") != "format":
            continue
        text = d["text"].lower()
        if "json" in text:
            results[d["id"]] = _contains_valid_json(response)
        elif "bullet" in text:
            results[d["id"]] = bool(re.search(r"^\s*[-*•]\s+", response, re.MULTILINE))
        elif "heading" in text or "header" in text:
            results[d["id"]] = bool(re.search(r"^#{1,6}\s+", response, re.MULTILINE))
        else:
            word_cap = re.search(r"(?:under|fewer than|less than|max(?:imum)?(?: of)?)\s+(\d+)\s+words", text)
            if word_cap:
                results[d["id"]] = len(response.split()) <= int(word_cap.group(1))
    return results


def _contains_valid_json(response: str) -> bool:
    """True when the response is JSON or contains a valid fenced JSON block."""
    candidates = [response.strip()]
    candidates += re.findall(r"```(?:json)?\s*(.*?)```", response, re.DOTALL)
    for cand in candidates:
        try:
            json.loads(cand.strip())
            return True
        except (ValueError, TypeError):
            continue
    return False


async def judge_adherence(
    question: str,
    response: str,
    directives: list[dict],
    *,
    judge_model: str | None = None,
) -> dict:
    """LLM-judge a response against the directive checklist.

    Returns:
        {
          "score": float | None,        # passed / (passed + failed), None if nothing applicable
          "results": [{"id", "verdict", "reasoning", "deterministic": bool}],
        }

    Deterministic format checks override the judge verdict where available
    (exact beats estimated).
    """
    directive_lines = "\n".join(f'- [{d["id"]}] ({d["kind"]}) {d["text"]}' for d in directives)
    model = judge_model or DEFAULT_EVAL_MODEL

    async def _call():
        return await chat_completion(
            model,
            [{"role": "user", "content": _JUDGE_PROMPT.format(
                directives=directive_lines,
                question=question[:4000],
                response=response[:12000],
            )}],
            {"temperature": 0.0, "max_tokens": 3000},
        )

    raw = await with_backoff(_call, attempts=3, label="skill-adherence-judge")
    data = _extract_json_object(raw["content"])

    by_id = {d["id"]: d for d in directives}
    deterministic = check_format_rules(response, directives)
    results = []
    seen: set[str] = set()
    for r in data.get("results", []):
        did = r.get("id")
        if did not in by_id or did in seen:
            continue
        seen.add(did)
        verdict = r.get("verdict") if r.get("verdict") in ("pass", "fail", "not_applicable") else "fail"
        is_det = did in deterministic
        if is_det:
            verdict = "pass" if deterministic[did] else "fail"
        results.append({
            "id": did,
            "verdict": verdict,
            "reasoning": str(r.get("reasoning", ""))[:500],
            "deterministic": is_det,
        })
    # Directives the judge skipped count as failures — silence is not compliance.
    for did in by_id:
        if did not in seen:
            results.append({
                "id": did,
                "verdict": "fail",
                "reasoning": "Judge returned no verdict for this directive",
                "deterministic": False,
            })

    passed = sum(1 for r in results if r["verdict"] == "pass")
    failed = sum(1 for r in results if r["verdict"] == "fail")
    score = passed / (passed + failed) if (passed + failed) > 0 else None
    return {"score": score, "results": results, "judge_usage": raw.get("usage", {})}
