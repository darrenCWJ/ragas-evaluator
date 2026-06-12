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

# Relative file references inside a skill: markdown links and bare mentions of
# files in conventional subdirectories (references/, scripts/, assets/...).
_MD_LINK_RE = re.compile(r"\[[^\]\n]{0,200}\]\(([^)\s]{1,300})\)")
_BARE_REF_RE = re.compile(
    r"\b((?:references|reference|scripts|assets|examples|docs)/[\w./-]{1,200})", re.IGNORECASE
)

# Phrases that mark a skill as needing user interaction mid-flow.
_INTERACTION_RE = re.compile(
    r"ask(?:s|ing)? the user|prompt(?:s|ing)? the user|ask(?: a)? clarifying"
    r"|AskUserQuestion|wait for (?:the )?user|user(?:'s)? (?:confirmation|approval|input)",
    re.IGNORECASE,
)


def referenced_paths(content: str) -> list[str]:
    """Relative file paths the skill references (progressive disclosure)."""
    paths: list[str] = []
    seen: set[str] = set()
    for match in list(_MD_LINK_RE.finditer(content)) + list(_BARE_REF_RE.finditer(content)):
        # Trailing sentence punctuation is part of the prose, not the path.
        raw = match.group(1).strip().lstrip("./").rstrip(".,;:)")
        if not raw or raw in seen:
            continue
        # Skip URLs, anchors, and absolute paths
        if "://" in raw or raw.startswith(("#", "/", "mailto:")):
            continue
        seen.add(raw)
        paths.append(raw)
    return paths


def detect_interaction(content: str) -> bool:
    """True when the skill instructs the assistant to ask the user questions."""
    return bool(_INTERACTION_RE.search(content))

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
    """Pull `name:` out of YAML frontmatter when present.

    String scanning instead of a lazy-dotall regex — the content is
    user-uploaded, and `^---\\s*\\n(.*?)\\n---` is polynomial on adversarial
    input (CodeQL py/polynomial-redos).
    """
    if not content.startswith("---"):
        return None
    first_newline = content.find("\n")
    if first_newline == -1 or content[3:first_newline].strip():
        return None
    end = content.find("\n---", first_newline)
    if end == -1:
        return None
    for line in content[first_newline + 1 : end].splitlines():
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
        "referenced_paths": referenced_paths(content),
        "interaction_required": detect_interaction(content),
    }
