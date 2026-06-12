"""Unit tests for the Skill Arena: parser, adherence scoring, and aggregation."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from evaluation.skills.adherence import check_format_rules, judge_adherence
from evaluation.skills.parser import _extract_json_object, _frontmatter_name, parse_skill

pytestmark = pytest.mark.unit


SKILL_MD = """---
name: support-tone
description: Customer support response style
---

# Support tone

- Always greet the customer by restating their problem.
- Never promise refunds without manager approval.
- Respond in valid JSON with keys "reply" and "next_steps".
"""


class TestParserHelpers:
    def test_extract_json_plain(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_extract_json_fenced(self):
        text = 'Here you go:\n```json\n{"a": 1}\n```\nDone.'
        assert _extract_json_object(text) == {"a": 1}

    def test_extract_json_trailing_noise(self):
        assert _extract_json_object('{"a": {"b": 2}} trailing') == {"a": {"b": 2}}

    def test_frontmatter_name(self):
        assert _frontmatter_name(SKILL_MD) == "support-tone"

    def test_frontmatter_name_missing(self):
        assert _frontmatter_name("# no frontmatter") is None


class TestParseSkill:
    async def test_parses_directives(self):
        llm_reply = {
            "content": json.dumps({
                "name": "Support tone",
                "summary": "Polite support responses",
                "directives": [
                    {"id": "d1", "text": "Greet by restating the problem", "kind": "behavior"},
                    {"id": "d2", "text": "Never promise refunds", "kind": "prohibition"},
                    {"id": "d3", "text": "Respond in valid JSON", "kind": "format",
                     "machine_checkable": True},
                ],
            }),
            "usage": {},
        }
        with patch("evaluation.skills.parser.chat_completion", new=AsyncMock(return_value=llm_reply)):
            parsed = await parse_skill(SKILL_MD)
        assert parsed["name"] == "support-tone"  # frontmatter wins
        assert len(parsed["directives"]) == 3
        assert parsed["directives"][2]["machine_checkable"] is True

    async def test_rejects_empty_directives(self):
        llm_reply = {"content": json.dumps({"name": "x", "directives": []}), "usage": {}}
        with patch("evaluation.skills.parser.chat_completion", new=AsyncMock(return_value=llm_reply)):
            with pytest.raises(ValueError, match="No testable directives"):
                await parse_skill(SKILL_MD)

    async def test_invalid_kind_defaults_to_behavior(self):
        llm_reply = {
            "content": json.dumps({
                "directives": [{"id": "d1", "text": "Do the thing", "kind": "banana"}],
            }),
            "usage": {},
        }
        with patch("evaluation.skills.parser.chat_completion", new=AsyncMock(return_value=llm_reply)):
            parsed = await parse_skill("# minimal skill content here")
        assert parsed["directives"][0]["kind"] == "behavior"


class TestFormatRules:
    DIRECTIVES = [
        {"id": "d1", "text": "Respond in valid JSON", "kind": "format", "machine_checkable": True},
        {"id": "d2", "text": "Use bullet points", "kind": "format", "machine_checkable": True},
        {"id": "d3", "text": "Stay under 50 words", "kind": "format", "machine_checkable": True},
        {"id": "d4", "text": "Be polite", "kind": "tone", "machine_checkable": False},
    ]

    def test_json_pass(self):
        results = check_format_rules('{"reply": "hi"}', self.DIRECTIVES)
        assert results["d1"] is True

    def test_json_fenced_pass(self):
        results = check_format_rules('Sure:\n```json\n{"reply": "hi"}\n```', self.DIRECTIVES)
        assert results["d1"] is True

    def test_json_fail(self):
        assert check_format_rules("plain prose answer", self.DIRECTIVES)["d1"] is False

    def test_bullets(self):
        assert check_format_rules("- one\n- two", self.DIRECTIVES)["d2"] is True
        assert check_format_rules("one two", self.DIRECTIVES)["d2"] is False

    def test_word_cap(self):
        assert check_format_rules("short answer", self.DIRECTIVES)["d3"] is True
        assert check_format_rules("word " * 60, self.DIRECTIVES)["d3"] is False

    def test_non_checkable_skipped(self):
        assert "d4" not in check_format_rules("anything", self.DIRECTIVES)


class TestJudgeAdherence:
    DIRECTIVES = [
        {"id": "d1", "text": "Greet politely", "kind": "behavior", "machine_checkable": False},
        {"id": "d2", "text": "Respond in valid JSON", "kind": "format", "machine_checkable": True},
        {"id": "d3", "text": "Never mention competitors", "kind": "prohibition", "machine_checkable": False},
    ]

    async def test_scores_and_deterministic_override(self):
        # Judge claims d2 passes, but the response is NOT valid JSON —
        # the deterministic check must override the judge.
        judge_reply = {
            "content": json.dumps({"results": [
                {"id": "d1", "verdict": "pass", "reasoning": "greets"},
                {"id": "d2", "verdict": "pass", "reasoning": "looks like json"},
                {"id": "d3", "verdict": "fail", "reasoning": "mentions rival"},
            ]}),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        with patch("evaluation.skills.adherence.chat_completion", new=AsyncMock(return_value=judge_reply)):
            out = await judge_adherence("q", "Hello! plain text", self.DIRECTIVES)
        by_id = {r["id"]: r for r in out["results"]}
        assert by_id["d2"]["verdict"] == "fail"
        assert by_id["d2"]["deterministic"] is True
        assert out["score"] == pytest.approx(1 / 3)

    async def test_missing_verdicts_count_as_fail(self):
        judge_reply = {
            "content": json.dumps({"results": [
                {"id": "d1", "verdict": "pass", "reasoning": "ok"},
            ]}),
            "usage": {},
        }
        with patch("evaluation.skills.adherence.chat_completion", new=AsyncMock(return_value=judge_reply)):
            out = await judge_adherence("q", '{"ok": true}', self.DIRECTIVES)
        by_id = {r["id"]: r for r in out["results"]}
        assert by_id["d3"]["verdict"] == "fail"
        assert "no verdict" in by_id["d3"]["reasoning"].lower()

    async def test_not_applicable_excluded_from_score(self):
        judge_reply = {
            "content": json.dumps({"results": [
                {"id": "d1", "verdict": "pass", "reasoning": "ok"},
                {"id": "d2", "verdict": "not_applicable", "reasoning": "n/a"},
                {"id": "d3", "verdict": "not_applicable", "reasoning": "n/a"},
            ]}),
            "usage": {},
        }
        directives = [
            {"id": "d1", "text": "Greet politely", "kind": "behavior", "machine_checkable": False},
            {"id": "d2", "text": "When asked about pricing, link the docs", "kind": "behavior",
             "machine_checkable": False},
            {"id": "d3", "text": "When refunds come up, escalate", "kind": "behavior",
             "machine_checkable": False},
        ]
        with patch("evaluation.skills.adherence.chat_completion", new=AsyncMock(return_value=judge_reply)):
            out = await judge_adherence("q", "Hello!", directives)
        assert out["score"] == 1.0
