"""Integration tests for sweep routes (background runner patched out)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import db.init
import main

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def runner_mock():
    with patch("app.routes.sweeps.run_sweep_background", AsyncMock()) as mock:
        yield mock


@pytest.fixture
def project(client):
    name = f"sweep-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


@pytest.fixture
def seeded(project):
    """Chunk/embedding/rag configs + a test set with one approved question."""
    conn = db.init.get_db()
    try:
        cc = conn.execute(
            "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, 'cc', 'recursive', '{}')",
            (project,),
        ).lastrowid
        ec = conn.execute(
            "INSERT INTO embedding_configs (project_id, name, type, model_name) VALUES (?, 'ec', 'dense_openai', 'text-embedding-3-small')",
            (project,),
        ).lastrowid
        rc = conn.execute(
            "INSERT INTO rag_configs (project_id, name, embedding_config_id, chunk_config_id, search_type, llm_model, top_k, response_mode, max_steps) "
            "VALUES (?, 'base', ?, ?, 'dense', 'gpt-4o-mini', 5, 'single_shot', 3)",
            (project, ec, cc),
        ).lastrowid
        ts = conn.execute(
            "INSERT INTO test_sets (project_id, name) VALUES (?, 'sweep-set')", (project,)
        ).lastrowid
        conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, status) VALUES (?, 'q?', 'a', 'approved')",
            (ts,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"pid": project, "rc": rc, "ts": ts}


VALID_GRID = {"top_k": [3, 5], "score_threshold": [0.2, 0.4]}


class TestCreateSweep:
    def test_creates_sweep_and_runs(self, client, seeded, runner_mock):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/sweeps",
            json={
                "name": "grid-1",
                "test_set_id": seeded["ts"],
                "rag_config_id": seeded["rc"],
                "grid": VALID_GRID,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["num_runs"] == 4
        assert body["status"] == "pending"
        assert body["metrics"]  # judge-free defaults applied
        runner_mock.assert_called_once_with(body["id"])

        detail = client.get(f"/api/projects/{seeded['pid']}/sweeps/{body['id']}").json()
        assert len(detail["runs"]) == 4
        assert all(r["status"] == "pending" for r in detail["runs"])

    def test_rejects_unsweepable_field(self, client, seeded, runner_mock):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/sweeps",
            json={
                "name": "bad",
                "test_set_id": seeded["ts"],
                "rag_config_id": seeded["rc"],
                "grid": {"search_type": ["dense", "sparse"]},
            },
        )
        assert resp.status_code == 422
        assert "Unsweepable" in resp.text

    def test_rejects_oversized_grid(self, client, seeded, runner_mock):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/sweeps",
            json={
                "name": "huge",
                "test_set_id": seeded["ts"],
                "rag_config_id": seeded["rc"],
                "grid": {"top_k": list(range(1, 8)), "alpha": [0.1, 0.3, 0.5], "num_expansions": [1, 2, 3]},
            },
        )
        assert resp.status_code == 422
        assert "limit" in resp.text

    def test_rejects_unknown_metric(self, client, seeded, runner_mock):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/sweeps",
            json={
                "name": "bad-metric",
                "test_set_id": seeded["ts"],
                "rag_config_id": seeded["rc"],
                "grid": {"top_k": [3]},
                "metrics": ["not_a_metric"],
            },
        )
        assert resp.status_code == 400
        assert "Unknown metrics" in resp.text

    def test_rejects_missing_test_set(self, client, seeded, runner_mock):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/sweeps",
            json={
                "name": "no-ts",
                "test_set_id": 999999,
                "rag_config_id": seeded["rc"],
                "grid": {"top_k": [3]},
            },
        )
        assert resp.status_code == 422


class TestSweepLifecycle:
    def _create(self, client, seeded) -> int:
        resp = client.post(
            f"/api/projects/{seeded['pid']}/sweeps",
            json={
                "name": "lifecycle",
                "test_set_id": seeded["ts"],
                "rag_config_id": seeded["rc"],
                "grid": {"top_k": [3, 5]},
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def test_list_includes_run_counts(self, client, seeded, runner_mock):
        sid = self._create(client, seeded)
        sweeps = client.get(f"/api/projects/{seeded['pid']}/sweeps").json()
        entry = next(s for s in sweeps if s["id"] == sid)
        assert entry["run_counts"] == {"pending": 2}

    def test_leaderboard_empty_before_results(self, client, seeded, runner_mock):
        sid = self._create(client, seeded)
        board = client.get(f"/api/projects/{seeded['pid']}/sweeps/{sid}/leaderboard").json()
        assert len(board["leaderboard"]) == 2
        assert all(e["aggregate_metrics"] is None for e in board["leaderboard"])

    def test_cancel_then_delete(self, client, seeded, runner_mock):
        sid = self._create(client, seeded)

        resp = client.post(f"/api/projects/{seeded['pid']}/sweeps/{sid}/cancel")
        assert resp.status_code == 200
        detail = client.get(f"/api/projects/{seeded['pid']}/sweeps/{sid}").json()
        assert detail["status"] == "cancelled"
        assert all(r["status"] == "cancelled" for r in detail["runs"])

        # Cancelling again conflicts
        assert client.post(f"/api/projects/{seeded['pid']}/sweeps/{sid}/cancel").status_code == 409

        assert client.delete(f"/api/projects/{seeded['pid']}/sweeps/{sid}").status_code == 204
        assert client.get(f"/api/projects/{seeded['pid']}/sweeps/{sid}").status_code == 404
