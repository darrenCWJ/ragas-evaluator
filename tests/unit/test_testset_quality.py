"""Unit tests for test-set quality audit and the refusal_accuracy metric."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from evaluation.metrics import refusal_accuracy
from evaluation.testset_quality import (
    audit_question,
    deterministic_checks,
    summarize_audit,
)

pytestmark = pytest.mark.unit


class TestDeterministicChecks:
    def test_clean_question_no_flags(self):
        flags = deterministic_checks(
            "What is the refund window for annual plans?",
            "Annual plans can be refunded within 30 days.",
            ["Refunds: annual plans may be refunded within 30 days of purchase."],
        )
        assert flags == []

    def test_too_short(self):
        assert "too_short" in deterministic_checks("Why?", "Because.", [])

    def test_no_reference(self):
        assert "no_reference" in deterministic_checks("What is the policy on refunds?", "  ", [])

    def test_grounded_type_without_contexts(self):
        flags = deterministic_checks(
            "What is the refund policy?", "30 days.",
            [], question_type="single_hop_specific_query_synthesizer",
        )
        assert "no_contexts" in flags

    def test_verbatim_leakage(self):
        context = (
            "The quarterly maintenance procedure requires operators to flush the "
            "coolant system before replacing the filter assembly."
        )
        leaky_question = (
            "Why does the quarterly maintenance procedure requires operators to "
            "flush the coolant system before doing anything else?"
        )
        flags = deterministic_checks(leaky_question, "Because of corrosion.", [context])
        assert "verbatim_leakage" in flags

    def test_paraphrased_question_not_leakage(self):
        context = (
            "The quarterly maintenance procedure requires operators to flush the "
            "coolant system before replacing the filter assembly."
        )
        question = "What must be done to the coolant before a filter swap?"
        assert "verbatim_leakage" not in deterministic_checks(question, "Flush it.", [context])


class TestAuditQuestion:
    async def test_llm_flags_merge(self):
        llm_reply = {
            "content": json.dumps({
                "grounded": False, "self_contained": True, "non_trivial": True,
                "reasoning": "Reference answer invents a number not in the context",
            }),
            "usage": {},
        }
        q = {
            "id": 1,
            "question": "What is the refund window for annual plans?",
            "reference_answer": "60 days.",
            "reference_contexts": ["Refunds: 30 days."],
            "question_type": "",
            "metadata": {},
        }
        with patch("evaluation.testset_quality.chat_completion", new=AsyncMock(return_value=llm_reply)):
            result = await audit_question(q)
        assert result["flags"] == ["ungrounded"]
        assert result["score"] == 0.75
        assert "invents" in result["reasoning"]

    async def test_refusal_questions_skip_llm_and_no_contexts_flag(self):
        q = {
            "id": 2,
            "question": "What is the CEO's shoe size according to the docs?",
            "reference_answer": "Not available in the knowledge base.",
            "reference_contexts": [],
            "question_type": "out_of_knowledge_base",
            "metadata": {"expected_behavior": "refusal"},
        }
        mock = AsyncMock()
        with patch("evaluation.testset_quality.chat_completion", new=mock):
            result = await audit_question(q)
        mock.assert_not_called()
        assert result["flags"] == []
        assert result["score"] == 1.0

    async def test_llm_failure_does_not_break_audit(self):
        q = {
            "id": 3,
            "question": "What is the refund window for annual plans?",
            "reference_answer": "30 days.",
            "reference_contexts": ["Refunds: 30 days."],
            "question_type": "",
            "metadata": {},
        }
        with patch(
            "evaluation.testset_quality.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("api down")),
        ):
            result = await audit_question(q)
        assert result["score"] == 1.0  # only deterministic flags counted
        assert "unavailable" in result["reasoning"]


class TestSummarize:
    def test_summary_shape(self):
        assessments = [
            (1, {"score": 1.0, "flags": [], "reasoning": ""}),
            (2, {"score": 0.5, "flags": ["ungrounded", "trivial"], "reasoning": "x"}),
            (3, {"score": 0.75, "flags": ["trivial"], "reasoning": "y"}),
        ]
        s = summarize_audit(assessments)
        assert s["audited"] == 3
        assert s["avg_score"] == 0.75
        assert s["flag_counts"] == {"trivial": 2, "ungrounded": 1}
        assert s["flagged_question_ids"] == [2, 3]

    def test_empty(self):
        assert summarize_audit([])["audited"] == 0


class TestRefusalAccuracy:
    async def test_non_refusal_question_returns_none(self):
        result = await refusal_accuracy.score(None, "q", "a", {"other": True})
        assert result is None
        result = await refusal_accuracy.score(None, "q", "a", None)
        assert result is None

    @pytest.mark.parametrize(
        ("verdict", "expected"),
        [("refused", 1.0), ("hedged", 0.5), ("fabricated", 0.0)],
    )
    async def test_verdict_scores(self, verdict, expected):
        reply = {"content": json.dumps({"verdict": verdict, "reasoning": "r"}), "usage": {}}
        with patch("evaluation.metrics.refusal_accuracy.chat_completion", new=AsyncMock(return_value=reply)):
            score = await refusal_accuracy.score(
                None, "What's the CEO's shoe size?", "I don't have that information.",
                {"expected_behavior": "refusal"},
            )
        assert score == expected

    async def test_empty_answer_scores_zero(self):
        score = await refusal_accuracy.score(None, "q", "", {"expected_behavior": "refusal"})
        assert score == 0.0
