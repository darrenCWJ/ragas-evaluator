"""Integration tests for get_project_report and get_experiment_trends endpoints."""

import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_reports.db"
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


def _insert_test_set(conn, project_id):
    cur = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, ?)", (project_id, "Set")
    )
    conn.commit()
    return cur.lastrowid


def _insert_bot_config(conn, project_id, name="Bot", connector_type="openai"):
    cur = conn.execute(
        "INSERT INTO bot_configs (project_id, name, connector_type, config_json) VALUES (?, ?, ?, ?)",
        (project_id, name, connector_type, "{}"),
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


def _insert_experiment(conn, project_id, test_set_id, name="Exp",
                        bot_config_id=None, rag_config_id=None, status="completed"):
    cur = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, bot_config_id, rag_config_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, test_set_id, name, "gpt-4o-mini", bot_config_id, rag_config_id, status),
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


class TestGetProjectReport:
    async def test_project_not_found(self, client):
        ac, _ = client
        resp = await ac.get("/api/projects/99999/report")
        assert resp.status_code == 404

    async def test_empty_report(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        resp = await ac.get(f"/api/projects/{pid}/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_experiments"] == 0
        assert data["experiments"] == []
        assert data["overall_metrics"] is None

    async def test_pending_excluded(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_experiment(conn, pid, ts_id, status="pending")
        resp = await ac.get(f"/api/projects/{pid}/report")
        assert resp.json()["total_experiments"] == 0

    async def test_aggregate_metrics(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q = _insert_question(conn, ts_id)
        exp_id = _insert_experiment(conn, pid, ts_id)
        _insert_result(conn, exp_id, q, {"faithfulness": 0.8, "answer_relevancy": 0.6})

        resp = await ac.get(f"/api/projects/{pid}/report")
        data = resp.json()
        assert data["total_experiments"] == 1
        exp = data["experiments"][0]
        assert exp["aggregate_metrics"]["faithfulness"] == pytest.approx(0.8, abs=0.001)
        assert exp["aggregate_metrics"]["answer_relevancy"] == pytest.approx(0.6, abs=0.001)
        assert exp["result_count"] == 1

    async def test_bot_config_name(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        bc_id = _insert_bot_config(conn, pid, name="My Bot")
        _insert_experiment(conn, pid, ts_id, bot_config_id=bc_id)

        resp = await ac.get(f"/api/projects/{pid}/report")
        exp = resp.json()["experiments"][0]
        assert exp["bot_config_name"] == "My Bot"
        assert exp["bot_config_id"] == bc_id

    async def test_rag_config_name(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        rc_id = _insert_rag_config(conn, pid, name="My RAG")
        _insert_experiment(conn, pid, ts_id, rag_config_id=rc_id)

        resp = await ac.get(f"/api/projects/{pid}/report")
        exp = resp.json()["experiments"][0]
        assert exp["rag_config_name"] == "My RAG"

    async def test_overall_metrics_across_experiments(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q = _insert_question(conn, ts_id)
        exp1_id = _insert_experiment(conn, pid, ts_id, name="E1")
        exp2_id = _insert_experiment(conn, pid, ts_id, name="E2")
        _insert_result(conn, exp1_id, q, {"faithfulness": 1.0})
        _insert_result(conn, exp2_id, q, {"faithfulness": 0.0})

        resp = await ac.get(f"/api/projects/{pid}/report")
        data = resp.json()
        assert data["total_experiments"] == 2
        assert data["overall_metrics"]["faithfulness"] == pytest.approx(0.5, abs=0.001)

    async def test_bot_summary(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        bc_id = _insert_bot_config(conn, pid, name="BotA")
        q = _insert_question(conn, ts_id)
        exp_id = _insert_experiment(conn, pid, ts_id, bot_config_id=bc_id)
        _insert_result(conn, exp_id, q, {"faithfulness": 0.9})

        resp = await ac.get(f"/api/projects/{pid}/report")
        summary = resp.json()["bot_summary"]
        assert len(summary) == 1
        assert summary[0]["bot_config_name"] == "BotA"
        assert summary[0]["experiment_count"] == 1
        assert summary[0]["aggregate_metrics"]["faithfulness"] == pytest.approx(0.9, abs=0.001)


class TestGetExperimentTrends:
    async def test_project_not_found(self, client):
        ac, _ = client
        resp = await ac.get("/api/projects/99999/report/trends")
        assert resp.status_code == 404

    async def test_empty_trends(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        resp = await ac.get(f"/api/projects/{pid}/report/trends")
        assert resp.status_code == 200
        assert resp.json()["points"] == []

    async def test_overall_trend(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q = _insert_question(conn, ts_id)
        exp1_id = _insert_experiment(conn, pid, ts_id, name="E1")
        exp2_id = _insert_experiment(conn, pid, ts_id, name="E2")
        _insert_result(conn, exp1_id, q, {"faithfulness": 0.5})
        _insert_result(conn, exp2_id, q, {"faithfulness": 1.0})

        resp = await ac.get(f"/api/projects/{pid}/report/trends?metric=overall")
        data = resp.json()
        assert data["metric"] == "overall"
        points = {p["experiment_name"]: p["value"] for p in data["points"]}
        assert points["E1"] == pytest.approx(0.5, abs=0.001)
        assert points["E2"] == pytest.approx(1.0, abs=0.001)

    async def test_specific_metric_trend(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q = _insert_question(conn, ts_id)
        exp_id = _insert_experiment(conn, pid, ts_id)
        _insert_result(conn, exp_id, q, {"faithfulness": 0.75})

        resp = await ac.get(f"/api/projects/{pid}/report/trends?metric=faithfulness")
        points = resp.json()["points"]
        assert len(points) == 1
        assert points[0]["value"] == pytest.approx(0.75, abs=0.001)

    async def test_bot_config_filter(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        bc_id = _insert_bot_config(conn, pid)
        q = _insert_question(conn, ts_id)
        exp_with_bot = _insert_experiment(conn, pid, ts_id, name="WithBot", bot_config_id=bc_id)
        exp_no_bot = _insert_experiment(conn, pid, ts_id, name="NoBot")
        _insert_result(conn, exp_with_bot, q, {"faithfulness": 0.8})
        _insert_result(conn, exp_no_bot, q, {"faithfulness": 0.2})

        resp = await ac.get(f"/api/projects/{pid}/report/trends?bot_config_id={bc_id}")
        points = resp.json()["points"]
        assert len(points) == 1
        assert points[0]["experiment_name"] == "WithBot"

    async def test_multiple_experiments_batch(self, client):
        """All experiments in trends fetch correctly without N+1."""
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        q = _insert_question(conn, ts_id)
        for i in range(3):
            eid = _insert_experiment(conn, pid, ts_id, name=f"E{i}")
            _insert_result(conn, eid, q, {"faithfulness": i * 0.25})

        resp = await ac.get(f"/api/projects/{pid}/report/trends")
        assert len(resp.json()["points"]) == 3
