"""Unit tests for the suggestion engine's prompt-guardrail and category rules."""

import pytest

from evaluation.suggestions import (
    GUARDRAIL_SNIPPETS,
    apply_config_change,
    generate_suggestions,
)

pytestmark = pytest.mark.unit


def _by_field(suggestions, field):
    return [s for s in suggestions if s.get("config_field") == field]


class TestGuardrailRules:
    def test_low_faithfulness_yields_applicable_grounding_guardrail(self):
        out = generate_suggestions({"faithfulness": 0.5}, [])
        guardrails = _by_field(out, "system_prompt_append")
        assert len(guardrails) == 1
        assert guardrails[0]["suggested_value"] == GUARDRAIL_SNIPPETS["grounding"]
        assert guardrails[0]["category"] == "guardrail"

    def test_low_refusal_accuracy_yields_refusal_guardrail(self):
        out = generate_suggestions({"refusal_accuracy": 0.3}, [])
        guardrails = _by_field(out, "system_prompt_append")
        assert len(guardrails) == 1
        assert guardrails[0]["suggested_value"] == GUARDRAIL_SNIPPETS["refusal"]
        assert guardrails[0]["priority"] == "high"

    def test_high_noise_sensitivity_yields_noise_guardrail(self):
        # noise_sensitivity is an error rate: HIGH is bad
        out = generate_suggestions({"noise_sensitivity": 0.6}, [])
        guardrails = _by_field(out, "system_prompt_append")
        assert len(guardrails) == 1
        assert guardrails[0]["suggested_value"] == GUARDRAIL_SNIPPETS["noise_filter"]

    def test_good_noise_sensitivity_no_suggestion(self):
        assert generate_suggestions({"noise_sensitivity": 0.1}, []) == []

    def test_low_answer_relevancy_adds_persona_guardrail(self):
        out = generate_suggestions({"answer_relevancy": 0.5}, [])
        guardrails = _by_field(out, "system_prompt_append")
        assert len(guardrails) == 1
        assert GUARDRAIL_SNIPPETS["persona"] in guardrails[0]["suggested_value"]
        assert GUARDRAIL_SNIPPETS["directness"] in guardrails[0]["suggested_value"]
        # The response_mode suggestion still exists alongside
        assert len(_by_field(out, "response_mode")) == 1

    def test_healthy_metrics_no_guardrails(self):
        out = generate_suggestions(
            {"faithfulness": 0.9, "refusal_accuracy": 0.95, "answer_relevancy": 0.9}, []
        )
        assert _by_field(out, "system_prompt_append") == []


class TestCategoryRules:
    @staticmethod
    def _results(category_scores: dict[str, list[float]]):
        return [
            {"metrics": {"m": score}, "category": cat}
            for cat, scores in category_scores.items()
            for score in scores
        ]

    def test_weak_refusal_category_gets_refusal_snippet(self):
        results = self._results({
            "typical": [0.9, 0.9, 0.85, 0.9],
            "out_of_knowledge_base": [0.2, 0.3, 0.25],
        })
        out = generate_suggestions({"exact_match": 0.9}, results)
        gaps = [s for s in out if s["category"] == "category_gap"]
        assert len(gaps) == 1
        assert "out_of_knowledge_base" in gaps[0]["signal"]
        assert gaps[0]["suggested_value"] == GUARDRAIL_SNIPPETS["refusal"]
        assert gaps[0]["priority"] == "high"

    def test_multi_hop_category_gets_phased_reasoning(self):
        results = self._results({
            "typical": [0.9] * 5,
            "multi_hop_abstract_query_synthesizer": [0.4, 0.45, 0.5],
        })
        out = generate_suggestions({"exact_match": 0.9}, results)
        gaps = [s for s in out if s["category"] == "category_gap"]
        assert len(gaps) == 1
        assert gaps[0]["suggested_value"] == GUARDRAIL_SNIPPETS["phased_reasoning"]

    def test_unknown_weak_category_points_to_breakdown(self):
        results = self._results({
            "typical": [0.9] * 5,
            "pricing": [0.3, 0.3, 0.35],
        })
        out = generate_suggestions({"exact_match": 0.9}, results)
        gaps = [s for s in out if s["category"] == "category_gap"]
        assert len(gaps) == 1
        assert gaps[0]["config_field"] is None
        assert "breakdown" in gaps[0]["suggestion"]

    def test_small_categories_ignored(self):
        results = self._results({
            "typical": [0.9] * 5,
            "edge": [0.1, 0.2],  # only 2 questions — below evidence threshold
        })
        out = generate_suggestions({"exact_match": 0.9}, results)
        assert [s for s in out if s["category"] == "category_gap"] == []


class TestSystemPromptAppend:
    def test_appends_to_existing_prompt(self):
        config = {"system_prompt": "You are a helpful assistant."}
        updated, changes = apply_config_change(
            config, "system_prompt_append", GUARDRAIL_SNIPPETS["refusal"], None
        )
        assert updated["system_prompt"].startswith("You are a helpful assistant.")
        assert GUARDRAIL_SNIPPETS["refusal"] in updated["system_prompt"]
        assert changes["system_prompt"]["old"] == "You are a helpful assistant."

    def test_appends_to_empty_prompt(self):
        updated, _ = apply_config_change(
            {"system_prompt": None}, "system_prompt_append",
            GUARDRAIL_SNIPPETS["grounding"], None,
        )
        assert updated["system_prompt"] == GUARDRAIL_SNIPPETS["grounding"]

    def test_duplicate_guardrail_rejected(self):
        config = {"system_prompt": f"Base.\n\n{GUARDRAIL_SNIPPETS['refusal']}"}
        with pytest.raises(ValueError, match="already part"):
            apply_config_change(
                config, "system_prompt_append", GUARDRAIL_SNIPPETS["refusal"], None
            )

    def test_requires_value(self):
        with pytest.raises(ValueError, match="guardrail text"):
            apply_config_change({"system_prompt": ""}, "system_prompt_append", None, None)
