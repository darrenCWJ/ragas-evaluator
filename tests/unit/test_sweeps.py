"""Unit tests for the parameter-sweep service."""

import json

import pytest

from app.services.sweep_service import (
    create_sweep_experiment,
    expand_grid,
    params_label,
    sweep_leaderboard,
)

pytestmark = pytest.mark.unit


class TestExpandGrid:
    def test_cartesian_product_deterministic_order(self):
        combos = expand_grid({"top_k": [3, 5], "alpha": [0.3, 0.7]})
        assert len(combos) == 4
        # Keys sorted: alpha varies slowest.
        assert combos[0] == {"alpha": 0.3, "top_k": 3}
        assert combos[1] == {"alpha": 0.3, "top_k": 5}
        assert combos[-1] == {"alpha": 0.7, "top_k": 5}

    def test_single_param(self):
        assert expand_grid({"top_k": [1, 2, 3]}) == [
            {"top_k": 1},
            {"top_k": 2},
            {"top_k": 3},
        ]

    def test_label(self):
        assert params_label({"top_k": 5, "alpha": 0.3}) == "alpha=0.3, top_k=5"


@pytest.fixture
def sweep_db(sample_project):
    """Project with chunk/embedding/rag configs, a test set, and a sweep row."""
    conn, pid = sample_project
    cc = conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, 'cc', 'recursive', '{}')",
        (pid,),
    ).lastrowid
    ec = conn.execute(
        "INSERT INTO embedding_configs (project_id, name, type, model_name) VALUES (?, 'ec', 'dense_openai', 'text-embedding-3-small')",
        (pid,),
    ).lastrowid
    rc = conn.execute(
        "INSERT INTO rag_configs (project_id, name, embedding_config_id, chunk_config_id, search_type, llm_model, top_k, response_mode, max_steps, mmr_lambda) "
        "VALUES (?, 'base', ?, ?, 'dense', 'gpt-4o-mini', 5, 'single_shot', 3, 0.5)",
        (pid, ec, cc),
    ).lastrowid
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'sweep-set')", (pid,)
    ).lastrowid
    tq = conn.execute(
        "INSERT INTO test_questions (test_set_id, question, reference_answer, status) VALUES (?, 'q?', 'a', 'approved')",
        (ts,),
    ).lastrowid
    sweep = conn.execute(
        "INSERT INTO sweeps (project_id, name, test_set_id, base_rag_config_id, grid_json, metrics_json) "
        "VALUES (?, 'sweep-1', ?, ?, '{}', '[]')",
        (pid, ts, rc),
    ).lastrowid
    conn.commit()
    return conn, {"pid": pid, "cc": cc, "ec": ec, "rc": rc, "ts": ts, "tq": tq, "sweep": sweep}


class TestCreateSweepExperiment:
    def test_snapshot_applies_overrides_and_keeps_base(self, sweep_db):
        conn, ids = sweep_db
        sweep = conn.execute("SELECT * FROM sweeps WHERE id = ?", (ids["sweep"],)).fetchone()
        base = conn.execute("SELECT * FROM rag_configs WHERE id = ?", (ids["rc"],)).fetchone()

        exp_id = create_sweep_experiment(conn, sweep, base, {"top_k": 10, "score_threshold": 0.4})

        row = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        snapshot = json.loads(row["retrieval_config_json"])
        assert snapshot["top_k"] == 10  # overridden
        assert snapshot["score_threshold"] == 0.4  # overridden
        assert snapshot["mmr_lambda"] == 0.5  # inherited from base config
        assert snapshot["search_type"] == "dense"
        assert row["model"] == "gpt-4o-mini"
        assert row["rag_config_id"] is None
        assert row["status"] == "pending"
        assert "top_k=10" in row["name"]

    def test_llm_model_override(self, sweep_db):
        conn, ids = sweep_db
        sweep = conn.execute("SELECT * FROM sweeps WHERE id = ?", (ids["sweep"],)).fetchone()
        base = conn.execute("SELECT * FROM rag_configs WHERE id = ?", (ids["rc"],)).fetchone()

        exp_id = create_sweep_experiment(conn, sweep, base, {"llm_model": "gpt-4o"})

        row = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        assert row["model"] == "gpt-4o"


class TestSweepLeaderboard:
    def _add_run(self, conn, sweep_id, question_id, params, metrics_rows, *, status="completed"):
        exp_id = None
        if metrics_rows is not None:
            sweep = conn.execute("SELECT * FROM sweeps WHERE id = ?", (sweep_id,)).fetchone()
            exp_id = conn.execute(
                "INSERT INTO experiments (project_id, test_set_id, name, model, status) VALUES (?, ?, 'e', 'm', 'completed')",
                (sweep["project_id"], sweep["test_set_id"]),
            ).lastrowid
            for metrics in metrics_rows:
                conn.execute(
                    "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
                    "VALUES (?, ?, 'a', '[]', ?, '{}')",
                    (exp_id, question_id, json.dumps(metrics)),
                )
        conn.execute(
            "INSERT INTO sweep_runs (sweep_id, experiment_id, params_json, status) VALUES (?, ?, ?, ?)",
            (sweep_id, exp_id, json.dumps(params), status),
        )
        conn.commit()

    def test_ranks_by_retrieval_hit_rate_then_overall(self, sweep_db):
        conn, ids = sweep_db
        sid, tq = ids["sweep"], ids["tq"]
        self._add_run(conn, sid, tq, {"top_k": 3}, [{"retrieval_hit_rate": 0.5, "bleu_score": 0.9}])
        self._add_run(conn, sid, tq, {"top_k": 5}, [{"retrieval_hit_rate": 1.0, "bleu_score": 0.2}])
        self._add_run(conn, sid, tq, {"top_k": 8}, [{"bleu_score": 0.99}])  # no provenance
        self._add_run(conn, sid, tq, {"top_k": 13}, None, status="failed")  # never ran

        board = sweep_leaderboard(conn, sid)

        assert [e["params"]["top_k"] for e in board] == [5, 3, 8, 13]
        assert board[0]["aggregate_metrics"]["retrieval_hit_rate"] == 1.0
        assert board[-1]["aggregate_metrics"] is None
        assert board[-1]["status"] == "failed"

    def test_empty_sweep(self, sweep_db):
        conn, ids = sweep_db
        assert sweep_leaderboard(conn, ids["sweep"]) == []
