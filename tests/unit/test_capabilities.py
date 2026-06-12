"""Dataset capability model: detection + per-metric availability."""

import json

from evaluation.capabilities import (
    CATEGORY,
    CONTEXTS,
    REF_DATA,
    REF_SQL,
    TURNS,
    dataset_capabilities,
    metric_availability,
)


def _make_test_set(conn, project_id: int) -> int:
    conn.execute(
        "INSERT INTO test_sets (project_id, name, status) VALUES (?, 'caps', 'completed')",
        (project_id,),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _add_question(conn, test_set_id: int, **overrides):
    fields = {
        "question": "What is X?",
        "reference_answer": "X is Y.",
        "reference_contexts": None,
        "category": None,
        "status": "approved",
        "metadata_json": None,
    }
    fields.update(overrides)
    conn.execute(
        """INSERT INTO test_questions
           (test_set_id, question, reference_answer, reference_contexts, category, status, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            test_set_id,
            fields["question"],
            fields["reference_answer"],
            fields["reference_contexts"],
            fields["category"],
            fields["status"],
            fields["metadata_json"],
        ),
    )
    conn.commit()


class TestDatasetCapabilities:
    def test_bare_questions_have_no_capabilities(self, sample_project):
        conn, pid = sample_project
        ts = _make_test_set(conn, pid)
        _add_question(conn, ts)
        assert dataset_capabilities(conn, ts) == set()

    def test_detects_contexts_category_turns_sql_data(self, sample_project):
        conn, pid = sample_project
        ts = _make_test_set(conn, pid)
        _add_question(
            conn,
            ts,
            reference_contexts=json.dumps(["some context"]),
            category="refusal",
            metadata_json=json.dumps({
                "turns": ["hi"],
                "reference_sql": "SELECT 1",
                "reference_data": [{"a": 1}],
            }),
        )
        caps = dataset_capabilities(conn, ts)
        assert {CONTEXTS, CATEGORY, TURNS, REF_SQL, REF_DATA} <= caps

    def test_pending_questions_do_not_count(self, sample_project):
        conn, pid = sample_project
        ts = _make_test_set(conn, pid)
        _add_question(conn, ts, status="pending", category="refusal")
        assert dataset_capabilities(conn, ts) == set()

    def test_empty_contexts_do_not_count(self, sample_project):
        conn, pid = sample_project
        ts = _make_test_set(conn, pid)
        _add_question(conn, ts, reference_contexts="[]")
        assert CONTEXTS not in dataset_capabilities(conn, ts)


class TestMetricAvailability:
    def test_context_metrics_blocked_without_contexts(self):
        availability = metric_availability(set())
        assert not availability["faithfulness"]["available"]
        assert not availability["context_recall"]["available"]
        assert availability["exact_match"]["available"]
        assert availability["multi_llm_judge"]["available"]

    def test_runtime_contexts_unlock_context_metrics(self):
        availability = metric_availability(set(), runtime_contexts=True)
        assert availability["faithfulness"]["available"]
        assert availability["context_precision"]["available"]
        # Non-context requirements stay blocked
        assert not availability["sql_semantic_equivalence"]["available"]
        assert not availability["conversation_retention"]["available"]

    def test_specialized_requirements(self):
        availability = metric_availability({REF_SQL, TURNS, CATEGORY})
        assert availability["sql_semantic_equivalence"]["available"]
        assert availability["conversation_retention"]["available"]
        assert availability["refusal_accuracy"]["available"]
        assert not availability["datacompy_score"]["available"]

    def test_missing_lists_are_human_readable(self):
        availability = metric_availability(set())
        assert availability["sql_semantic_equivalence"]["missing"] == ["reference SQL"]
        assert availability["conversation_retention"]["missing"] == [
            "multi-turn conversation data"
        ]
