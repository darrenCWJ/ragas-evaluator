"""Integration tests for get_experiment_history endpoint."""

import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_history.db"
    import db.init as db_module

    with patch("db.init.DATABASE_PATH", db_path):
        db_module._connection = None
        conn = db_module.init_db()
        yield conn, db_path
        conn.close()
        db_module._connection = None


@pytest.fixture
async def client(test_db):
    conn, _ = test_db
    with patch("db.init.get_db", return_value=conn):
        from app import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, conn


def _insert_project(conn, name="Proj"):
    cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def _insert_test_set(conn, project_id, name="Set"):
    cur = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, ?)", (project_id, name)
    )
    conn.commit()
    return cur.lastrowid


def _insert_rag_config(conn, project_id, name="RC"):
    emb_id = conn.execute(
        "INSERT INTO embedding_configs (project_id, name, type) VALUES (?, ?, ?)",
        (project_id, name + "_emb", "openai"),
    ).lastrowid
    chunk_id = conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, ?, ?, ?)",
        (project_id, name + "_chunk", "recursive", "{}"),
    ).lastrowid
    cur = conn.execute(
        "INSERT INTO rag_configs (project_id, name, embedding_config_id, chunk_config_id, search_type, llm_model) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, name, emb_id, chunk_id, "semantic", "gpt-4o-mini"),
    )
    conn.commit()
    return cur.lastrowid


def _insert_experiment(conn, project_id, test_set_id, name="Exp", rag_config_id=None, status="completed"):
    cur = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, rag_config_id, status) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, test_set_id, name, "gpt-4o-mini", rag_config_id, status),
    )
    conn.commit()
    return cur.lastrowid


def _insert_question(conn, test_set_id):
    cur = conn.execute(
        "INSERT INTO test_questions (test_set_id, question, reference_answer) VALUES (?, ?, ?)",
        (test_set_id, "Q?", "A."),
    )
    conn.commit()
    return cur.lastrowid


def _insert_result(conn, experiment_id, question_id, metrics: dict):
    conn.execute(
        "INSERT INTO experiment_results (experiment_id, test_question_id, metrics_json) VALUES (?, ?, ?)",
        (experiment_id, question_id, json.dumps(metrics)),
    )
    conn.commit()


class TestGetExperimentHistory:
    async def test_project_not_found(self, client):
        ac, _ = client
        resp = await ac.get("/api/projects/99999/experiments/history")
        assert resp.status_code == 404

    async def test_empty_history(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        assert resp.status_code == 200
        assert resp.json() == {"experiments": []}

    async def test_pending_experiment_excluded(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_experiment(conn, pid, ts_id, status="pending")

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        assert resp.json() == {"experiments": []}

    async def test_rag_config_name_populated(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        rc_id = _insert_rag_config(conn, pid, name="My RAG Config")
        _insert_experiment(conn, pid, ts_id, rag_config_id=rc_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        exp = resp.json()["experiments"][0]
        assert exp["rag_config_name"] == "My RAG Config"

    async def test_no_rag_config(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_experiment(conn, pid, ts_id, rag_config_id=None)

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        exp = resp.json()["experiments"][0]
        assert exp["rag_config_name"] is None

    async def test_aggregate_metrics_and_overall_score(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q1 = _insert_question(conn, ts_id)
        q2 = _insert_question(conn, ts_id)
        exp_id = _insert_experiment(conn, pid, ts_id)
        _insert_result(conn, exp_id, q1, {"faithfulness": 0.8, "answer_relevancy": 0.6})
        _insert_result(conn, exp_id, q2, {"faithfulness": 0.4, "answer_relevancy": 1.0})

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        exp = resp.json()["experiments"][0]
        assert exp["result_count"] == 2
        assert exp["aggregate_metrics"]["faithfulness"] == pytest.approx(0.6, abs=0.001)
        assert exp["aggregate_metrics"]["answer_relevancy"] == pytest.approx(0.8, abs=0.001)
        assert exp["overall_score"] == pytest.approx(0.7, abs=0.001)

    async def test_null_only_metric_omitted(self, client):
        """Metrics that are all-null should not appear in aggregate_metrics."""
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q = _insert_question(conn, ts_id)
        exp_id = _insert_experiment(conn, pid, ts_id)
        _insert_result(conn, exp_id, q, {"faithfulness": 0.5, "never_set": None})

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        agg = resp.json()["experiments"][0]["aggregate_metrics"]
        assert "faithfulness" in agg
        assert "never_set" not in agg

    async def test_no_results(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        exp = resp.json()["experiments"][0]
        assert exp["result_count"] == 0
        assert exp["aggregate_metrics"] is None
        assert exp["overall_score"] is None

    async def test_multiple_experiments_batch(self, client):
        """Two experiments should both get correct metrics without N+1."""
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        rc1 = _insert_rag_config(conn, pid, name="RC1")
        rc2 = _insert_rag_config(conn, pid, name="RC2")
        q = _insert_question(conn, ts_id)

        exp1_id = _insert_experiment(conn, pid, ts_id, name="Exp1", rag_config_id=rc1)
        exp2_id = _insert_experiment(conn, pid, ts_id, name="Exp2", rag_config_id=rc2)
        _insert_result(conn, exp1_id, q, {"faithfulness": 1.0})
        _insert_result(conn, exp2_id, q, {"faithfulness": 0.0})

        resp = await ac.get(f"/api/projects/{pid}/experiments/history")
        assert resp.status_code == 200
        data = resp.json()["experiments"]
        assert len(data) == 2

        by_name = {e["name"]: e for e in data}
        assert by_name["Exp1"]["rag_config_name"] == "RC1"
        assert by_name["Exp1"]["aggregate_metrics"]["faithfulness"] == pytest.approx(1.0)
        assert by_name["Exp2"]["rag_config_name"] == "RC2"
        assert by_name["Exp2"]["aggregate_metrics"]["faithfulness"] == pytest.approx(0.0)
