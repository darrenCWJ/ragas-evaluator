"""Golden eval tests for multi_llm_judge aggregation logic.

Validates that aggregate_score and aggregate_criteria_score produce correct
scores from known verdicts, catching regressions in CI.
"""

import json
from pathlib import Path

import pytest

from evaluation.metrics.multi_llm_judge import aggregate_criteria_score, aggregate_score

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
GOLDEN_FILE = FIXTURES_DIR / "golden_multi_llm_judge.json"


def _load_case(case_id: str) -> dict:
    """Load a single golden case by id."""
    cases = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    for case in cases:
        if case["id"] == case_id:
            return case
    raise KeyError(f"Golden case '{case_id}' not found in {GOLDEN_FILE}")


# ---------------------------------------------------------------------------
# aggregate_score tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_aggregate_score_all_positive() -> None:
    """All evaluators give positive verdict — mean score must be 1.0."""
    case = _load_case("all_positive")
    result = aggregate_score(case["evaluations"], set(case["excluded_indices"]))
    assert case["expected_min"] <= result <= case["expected_max"], (
        f"Expected score in [{case['expected_min']}, {case['expected_max']}], got {result}"
    )


@pytest.mark.unit
def test_aggregate_score_all_critical() -> None:
    """All evaluators give critical verdict — mean score must be 0.0."""
    case = _load_case("all_critical")
    result = aggregate_score(case["evaluations"], set(case["excluded_indices"]))
    assert case["expected_min"] <= result <= case["expected_max"], (
        f"Expected score in [{case['expected_min']}, {case['expected_max']}], got {result}"
    )


@pytest.mark.unit
def test_aggregate_score_mixed_verdicts() -> None:
    """One positive, one mixed, one critical — mean score must be ~0.5."""
    case = _load_case("mixed_verdicts")
    result = aggregate_score(case["evaluations"], set(case["excluded_indices"]))
    assert case["expected_min"] <= result <= case["expected_max"], (
        f"Expected score in [{case['expected_min']}, {case['expected_max']}], got {result}"
    )


@pytest.mark.unit
def test_aggregate_score_with_exclusions() -> None:
    """Two critical evaluators excluded; only the positive one counts — score must be ~1.0."""
    case = _load_case("with_excluded")
    result = aggregate_score(case["evaluations"], set(case["excluded_indices"]))
    assert case["expected_min"] <= result <= case["expected_max"], (
        f"Expected score in [{case['expected_min']}, {case['expected_max']}], got {result}"
    )


# ---------------------------------------------------------------------------
# aggregate_criteria_score tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_aggregate_criteria_score_all_good() -> None:
    """All criteria evaluators score 1.0 — mean must be 1.0."""
    case = _load_case("all_criteria_good")
    result = aggregate_criteria_score(case["evaluations"], set(case["excluded_indices"]))
    assert case["expected_min"] <= result <= case["expected_max"], (
        f"Expected score in [{case['expected_min']}, {case['expected_max']}], got {result}"
    )


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_aggregate_score_empty_evaluations_returns_none() -> None:
    """Empty evaluations list (all evaluators failed) returns None, not 0.0."""
    result = aggregate_score([], set())
    assert result is None, f"Expected None for empty evaluations, got {result}"


@pytest.mark.unit
def test_aggregate_criteria_score_empty_evaluations_returns_none() -> None:
    """Empty evaluations list (all evaluators failed) returns None, not 0.0."""
    result = aggregate_criteria_score([], set())
    assert result is None, f"Expected None for empty evaluations, got {result}"


@pytest.mark.unit
def test_aggregate_score_all_excluded_falls_back_to_all_evaluators() -> None:
    """When all indices are excluded the function falls back to the full list."""
    evaluations = [
        {"evaluator_index": 0, "verdict": "positive", "score": 1.0, "reasoning": "", "claims": [], "model": "gpt-4o"},
        {"evaluator_index": 1, "verdict": "positive", "score": 1.0, "reasoning": "", "claims": [], "model": "gpt-4o"},
    ]
    # Exclude both — the implementation falls back to all evaluators, so the score
    # should still reflect the full list rather than returning 0.
    result = aggregate_score(evaluations, {0, 1})
    assert result == 1.0, f"Expected 1.0 fallback score, got {result}"


@pytest.mark.unit
def test_aggregate_score_unknown_verdict_treated_as_mixed() -> None:
    """An unrecognised verdict string defaults to 0.5 (mixed) via dict.get fallback."""
    evaluations = [
        {
            "evaluator_index": 0,
            "verdict": "unknown_verdict",
            "score": 0.5,
            "reasoning": "",
            "claims": [],
            "model": "gpt-4o",
        }
    ]
    result = aggregate_score(evaluations, set())
    assert result == 0.5, f"Expected 0.5 for unknown verdict, got {result}"
