"""Integration tests for list_experiments endpoint."""

import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_list.db"
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


def _insert_project(conn, name="Test Project"):
    cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def _insert_test_set(conn, project_id, name="Test Set"):
    cur = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, ?)",
        (project_id, name),
    )
    conn.commit()
    return cur.lastrowid


def _insert_question(conn, test_set_id, status="approved", reference_contexts=None, metadata_json=None):
    cur = conn.execute(
        "INSERT INTO test_questions (test_set_id, question, reference_answer, status, reference_contexts, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
        (test_set_id, "Q?", "A.", status, reference_contexts, metadata_json),
    )
    conn.commit()
    return cur.lastrowid


def _insert_bot_config(conn, project_id, connector_type="openai", config=None):
    cur = conn.execute(
        "INSERT INTO bot_configs (project_id, name, connector_type, config_json) VALUES (?, ?, ?, ?)",
        (project_id, "Bot", connector_type, json.dumps(config or {})),
    )
    conn.commit()
    return cur.lastrowid


def _insert_experiment(conn, project_id, test_set_id, name="Exp", bot_config_id=None):
    cur = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, bot_config_id) VALUES (?, ?, ?, ?, ?)",
        (project_id, test_set_id, name, "gpt-4o-mini", bot_config_id),
    )
    conn.commit()
    return cur.lastrowid


class TestListExperiments:
    async def test_empty_list(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        resp = await ac.get(f"/api/projects/{pid}/experiments")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_project_not_found(self, client):
        ac, _ = client
        resp = await ac.get("/api/projects/99999/experiments")
        assert resp.status_code == 404

    async def test_approved_question_count(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_question(conn, ts_id, status="approved")
        _insert_question(conn, ts_id, status="edited")
        _insert_question(conn, ts_id, status="pending")  # not counted
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["approved_question_count"] == 2

    async def test_test_set_name(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid, name="My Golden Set")
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        assert resp.json()[0]["test_set_name"] == "My Golden Set"

    async def test_has_reference_contexts_true(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_question(conn, ts_id, reference_contexts='["ctx1"]')
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        assert resp.json()[0]["has_reference_contexts"] is True

    async def test_has_reference_contexts_false(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_question(conn, ts_id, reference_contexts=None)
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        assert resp.json()[0]["has_reference_contexts"] is False

    async def test_has_reference_sql_and_data(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_question(conn, ts_id, metadata_json='{"reference_sql": "SELECT 1"}')
        _insert_question(conn, ts_id, metadata_json='{"reference_data": [{"col": "val"}]}')
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        exp = resp.json()[0]
        assert exp["has_reference_sql"] is True
        assert exp["has_reference_data"] is True

    async def test_no_reference_sql_or_data(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_question(conn, ts_id)
        _insert_experiment(conn, pid, ts_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        exp = resp.json()[0]
        assert exp["has_reference_sql"] is False
        assert exp["has_reference_data"] is False

    async def test_connector_type_and_bot_returns_contexts(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        bc_id = _insert_bot_config(conn, pid, connector_type="glean")
        _insert_experiment(conn, pid, ts_id, bot_config_id=bc_id)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        exp = resp.json()[0]
        assert exp["connector_type"] == "glean"
        assert exp["bot_returns_contexts"] is True

    async def test_no_bot_config(self, client):
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid)
        _insert_experiment(conn, pid, ts_id, bot_config_id=None)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        exp = resp.json()[0]
        assert exp["connector_type"] is None
        assert exp["bot_returns_contexts"] is False

    async def test_multiple_experiments_all_fields(self, client):
        """Two experiments with different configs both return correct fields."""
        ac, conn = client
        pid = _insert_project(conn)
        ts_id = _insert_test_set(conn, pid, name="Set A")
        _insert_question(conn, ts_id, status="approved", reference_contexts='["ctx"]')
        _insert_question(conn, ts_id, status="approved", metadata_json='{"reference_sql": "SELECT 1"}')

        bc_id = _insert_bot_config(conn, pid, connector_type="openai")
        _insert_experiment(conn, pid, ts_id, name="Exp1", bot_config_id=bc_id)
        _insert_experiment(conn, pid, ts_id, name="Exp2", bot_config_id=None)

        resp = await ac.get(f"/api/projects/{pid}/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        # Both should have the same test-set-derived fields
        for exp in data:
            assert exp["test_set_name"] == "Set A"
            assert exp["approved_question_count"] == 2
            assert exp["has_reference_contexts"] is True
            assert exp["has_reference_sql"] is True
            assert exp["has_reference_data"] is False

        # Find by name
        exp1 = next(e for e in data if e["name"] == "Exp1")
        exp2 = next(e for e in data if e["name"] == "Exp2")

        assert exp1["connector_type"] == "openai"
        assert exp1["bot_returns_contexts"] is False

        assert exp2["connector_type"] is None
        assert exp2["bot_returns_contexts"] is False
