"""Skill file parsing — extract testable directives from a SKILL.md-style document.

A *skill file* is a markdown/text instruction document given to an AI as
system context. To evaluate how well different models follow it, we first
distill the prose into a checklist of discrete, individually-judgeable
directives.
"""

import json
import logging
import re

from config import DEFAULT_EVAL_MODEL
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

# Directive kinds the extractor classifies into.
DIRECTIVE_KINDS = {"behavior", "format", "prohibition", "tone"}

_EXTRACTION_PROMPT = """You are analyzing a "skill file" — an instruction document given to an AI assistant as system context. Extract every TESTABLE directive: a discrete rule whose compliance can be judged by reading a single response.

SKILL FILE:
---
{content}
---

Return ONLY a JSON object:
{{
  "name": "<short name for this skill, from the document or inferred>",
  "summary": "<one-sentence summary of what this skill makes the assistant do>",
  "directives": [
    {{
      "id": "d1",
      "text": "<the rule, rephrased as a single imperative statement>",
      "kind": "behavior" | "format" | "prohibition" | "tone",
      "machine_checkable": <true only for mechanically verifiable format rules, e.g. "respond in valid JSON", "use bullet points", "stay under N words">
    }}
  ]
}}

Rules:
- Split compound instructions into separate directives.
- Skip meta-text (frontmatter descriptions, examples, version notes) that doesn't constrain responses.
- 3 to 25 directives. Prefer the most load-bearing rules when trimming.
"""


def _extract_json_object(text: str) -> dict:
    """Parse the first JSON object out of an LLM reply (handles code fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    if start == -1:
        return json.loads(text)
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


def _frontmatter_name(content: str) -> str | None:
    """Pull `name:` out of YAML frontmatter when present."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.strip().startswith("name:"):
            return line.split(":", 1)[1].strip().strip("\"'") or None
    return None


async def parse_skill(content: str, model: str | None = None) -> dict:
    """Extract a directive checklist from a skill file.

    Returns {"name", "summary", "directives": [...]}. Raises on LLM or
    parse failure — a skill without directives cannot be evaluated, so
    callers must surface the error rather than store an empty checklist.
    """
    eval_model = model or DEFAULT_EVAL_MODEL

    async def _call():
        return await chat_completion(
            eval_model,
            [{"role": "user", "content": _EXTRACTION_PROMPT.format(content=content[:24000])}],
            {"temperature": 0.0, "max_tokens": 4000},
        )

    result = await with_backoff(_call, attempts=3, label="skill-parse")
    data = _extract_json_object(result["content"])

    directives = []
    for i, d in enumerate(data.get("directives", []), 1):
        text = str(d.get("text", "")).strip()
        if not text:
            continue
        kind = d.get("kind") if d.get("kind") in DIRECTIVE_KINDS else "behavior"
        directives.append(
            {
                "id": d.get("id") or f"d{i}",
                "text": text,
                "kind": kind,
                "machine_checkable": bool(d.get("machine_checkable", False)),
            }
        )
    if not directives:
        raise ValueError("No testable directives could be extracted from the skill file")

    return {
        "name": _frontmatter_name(content) or str(data.get("name", "")).strip() or "Unnamed skill",
        "summary": str(data.get("summary", "")).strip(),
        "directives": directives,
    }
