"""Unit tests for judge calibration (human-agreement ranking of judge models)."""

import json

import pytest

from app.services.judge_calibration import (
    MIN_CALIBRATION_PAIRS,
    apply_judge_assignments,
    judge_calibration_report,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def annotated_db(sample_project):
    """Project with one experiment, rated results, and per-model judge evals."""
    conn, pid = sample_project
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'cal-set')", (pid,)
    ).lastrowid
    tq = conn.execute(
        "INSERT INTO test_questions (test_set_id, question, reference_answer, status) VALUES (?, 'q?', 'a', 'approved')",
        (ts,),
    ).lastrowid
    exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status) VALUES (?, ?, 'e', 'm', 'completed')",
        (pid, ts),
    ).lastrowid
    conn.commit()

    def add_rated_result(rating: str, judge_scores: dict[str, float]) -> int:
        rid = conn.execute(
            "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
            "VALUES (?, ?, 'resp', '[]', '{}', '{}')",
            (exp, tq),
        ).lastrowid
        conn.execute(
            "INSERT INTO human_annotations (experiment_result_id, rating) VALUES (?, ?)",
            (rid, rating),
        )
        for idx, (model, score) in enumerate(judge_scores.items()):
            verdict = "positive" if score >= 0.7 else ("mixed" if score >= 0.4 else "critical")
            conn.execute(
                "INSERT INTO multi_llm_evaluations (experiment_result_id, evaluator_index, verdict, score, claims_json, model) "
                "VALUES (?, ?, ?, ?, '[]', ?)",
                (rid, idx, verdict, score, model),
            )
        conn.commit()
        return rid

    return conn, pid, add_rated_result


class TestJudgeCalibrationReport:
    def test_ranks_models_by_human_agreement(self, annotated_db):
        conn, pid, add = annotated_db
        # good-judge matches the human bucket every time; bad-judge never does.
        for _ in range(MIN_CALIBRATION_PAIRS):
            add("accurate", {"good-judge": 0.9, "bad-judge": 0.1})

        report = judge_calibration_report(conn, pid)

        assert report["total_pairs"] == MIN_CALIBRATION_PAIRS * 2
        by_model = {m["model"]: m for m in report["models"]}
        assert by_model["good-judge"]["agreement_rate"] == 1.0
        assert by_model["bad-judge"]["agreement_rate"] == 0.0
        assert by_model["good-judge"]["calibrated"] is True
        assert report["models"][0]["model"] == "good-judge"
        # bad-judge is calibrated but below the 50% agreement floor.
        assert report["recommended_assignments"] == ["good-judge"]

    def test_uncalibrated_below_min_pairs(self, annotated_db):
        conn, pid, add = annotated_db
        add("accurate", {"sparse-judge": 0.9})

        report = judge_calibration_report(conn, pid)

        assert report["models"][0]["calibrated"] is False
        assert report["recommended_assignments"] is None

    def test_ignores_legacy_rows_without_model(self, annotated_db):
        conn, pid, add = annotated_db
        rid = add("accurate", {})
        conn.execute(
            "INSERT INTO multi_llm_evaluations (experiment_result_id, evaluator_index, verdict, score, claims_json, model) "
            "VALUES (?, 0, 'positive', 0.9, '[]', NULL)",
            (rid,),
        )
        conn.commit()

        report = judge_calibration_report(conn, pid)
        assert report["total_pairs"] == 0
        assert report["models"] == []

    def test_ignores_custom_metric_judges(self, annotated_db):
        conn, pid, add = annotated_db
        rid = add("accurate", {})
        conn.execute(
            "INSERT INTO multi_llm_evaluations (experiment_result_id, evaluator_index, verdict, score, claims_json, model, custom_metric_name) "
            "VALUES (?, 0, 'positive', 0.9, '[]', 'judge-x', 'my_custom')",
            (rid,),
        )
        conn.commit()

        assert judge_calibration_report(conn, pid)["total_pairs"] == 0

    def test_mean_abs_error_tiebreak(self, annotated_db):
        conn, pid, add = annotated_db
        # Both agree on the bucket each time, but tight-judge is closer to 1.0.
        for _ in range(MIN_CALIBRATION_PAIRS):
            add("accurate", {"loose-judge": 0.72, "tight-judge": 0.98})

        report = judge_calibration_report(conn, pid)

        assert [m["model"] for m in report["models"]] == ["tight-judge", "loose-judge"]
        assert report["recommended_assignments"] == ["tight-judge", "loose-judge"]


class TestApplyAssignments:
    def test_persists_to_project(self, annotated_db):
        conn, pid, _ = annotated_db
        applied = apply_judge_assignments(conn, pid, ["judge-a", "judge-b"])
        assert applied == ["judge-a", "judge-b"]
        row = conn.execute(
            "SELECT judge_model_assignments_json FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        assert json.loads(row["judge_model_assignments_json"]) == ["judge-a", "judge-b"]
