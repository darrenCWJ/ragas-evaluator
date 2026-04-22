"""Regression tests for the multi_llm_judge API routes.

Verifies that the 4 new endpoints are correctly wired and return sensible
status codes for both valid and invalid inputs.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_mlj(tmp_path):
    """Fresh SQLite database for multi-LLM judge tests."""
    db_path = tmp_path / "test_mlj.db"
    import db.init as db_module

    with patch("db.init.DATABASE_PATH", db_path):
        db_module._connection = None
        conn = db_module.init_db()
        yield conn
        conn.close()
        db_module._connection = None


@pytest.fixture
async def client(tmp_db_mlj):
    """Async test client with the real app and a patched DB connection."""
    import db.init as db_module
    from app import app

    with patch.object(db_module, "get_db", return_value=tmp_db_mlj):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def project_id(tmp_db_mlj):
    """Insert a test project and return its id."""
    tmp_db_mlj.execute("INSERT INTO projects (name) VALUES (?)", ("mlj-test-project",))
    tmp_db_mlj.commit()
    row = tmp_db_mlj.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


@pytest.fixture
def experiment_id(tmp_db_mlj, project_id):
    """Insert a minimal test_set + completed experiment and return the experiment id."""
    # test_sets is required by experiments (NOT NULL FK)
    tmp_db_mlj.execute(
        "INSERT INTO test_sets (project_id, name, status) VALUES (?, ?, ?)",
        (project_id, "mlj-test-set", "completed"),
    )
    tmp_db_mlj.commit()
    test_set_id = tmp_db_mlj.execute("SELECT last_insert_rowid()").fetchone()[0]

    tmp_db_mlj.execute(
        """INSERT INTO experiments
               (project_id, test_set_id, name, model, status)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, test_set_id, "test-exp", "gpt-4", "completed"),
    )
    tmp_db_mlj.commit()
    return tmp_db_mlj.execute("SELECT last_insert_rowid()").fetchone()[0]


@pytest.fixture
def result_id(tmp_db_mlj, experiment_id):
    """Insert a test_question + experiment_result and return the result id."""
    # test_questions requires test_set_id — look it up from the experiment
    test_set_id = tmp_db_mlj.execute(
        "SELECT test_set_id FROM experiments WHERE id = ?", (experiment_id,)
    ).fetchone()[0]

    tmp_db_mlj.execute(
        """INSERT INTO test_questions
               (test_set_id, question, reference_answer, status)
           VALUES (?, ?, ?, ?)""",
        (test_set_id, "What is 2+2?", "4", "pending"),
    )
    tmp_db_mlj.commit()
    question_id = tmp_db_mlj.execute("SELECT last_insert_rowid()").fetchone()[0]

    tmp_db_mlj.execute(
        """INSERT INTO experiment_results
               (experiment_id, test_question_id, metrics_json)
           VALUES (?, ?, ?)""",
        (experiment_id, question_id, "{}"),
    )
    tmp_db_mlj.commit()
    return tmp_db_mlj.execute("SELECT last_insert_rowid()").fetchone()[0]


# ---------------------------------------------------------------------------
# TestGetJudgeEvaluations
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetJudgeEvaluations:
    """GET /api/projects/{p}/experiments/{e}/results/{r}/judge-evaluations"""

    async def test_returns_404_for_missing_project(self, client):
        resp = await client.get(
            "/api/projects/99999/experiments/99999/results/99999/judge-evaluations"
        )
        assert resp.status_code == 404
        assert "Project not found" in resp.json()["detail"]

    async def test_returns_404_for_missing_experiment(self, client, project_id):
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/99999/results/99999/judge-evaluations"
        )
        assert resp.status_code == 404
        assert "Experiment not found" in resp.json()["detail"]

    async def test_returns_404_for_missing_result(self, client, project_id, experiment_id):
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/{experiment_id}"
            "/results/99999/judge-evaluations"
        )
        assert resp.status_code == 404
        assert "Result not found" in resp.json()["detail"]

    async def test_returns_200_with_empty_evaluations(
        self, client, project_id, experiment_id, result_id
    ):
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/{experiment_id}"
            f"/results/{result_id}/judge-evaluations"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result_id"] == result_id
        assert data["evaluations"] == []


# ---------------------------------------------------------------------------
# TestGetJudgeAnnotationSample
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetJudgeAnnotationSample:
    """GET /api/projects/{p}/experiments/{e}/judge-annotation-sample"""

    async def test_returns_404_for_missing_project(self, client):
        resp = await client.get(
            "/api/projects/99999/experiments/99999/judge-annotation-sample"
        )
        assert resp.status_code == 404
        assert "Project not found" in resp.json()["detail"]

    async def test_returns_404_for_missing_experiment(self, client, project_id):
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/99999/judge-annotation-sample"
        )
        assert resp.status_code == 404
        assert "Experiment not found" in resp.json()["detail"]

    async def test_returns_200_with_empty_sample(
        self, client, project_id, experiment_id
    ):
        """Experiment exists and is completed but has no multi_llm_evaluations rows."""
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/{experiment_id}"
            "/judge-annotation-sample"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_id"] == experiment_id
        assert data["total_results"] == 0
        assert data["sample_size"] == 0
        assert data["sample"] == []


# ---------------------------------------------------------------------------
# TestGetJudgeReliability
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetJudgeReliability:
    """GET /api/projects/{p}/experiments/{e}/judge-reliability"""

    async def test_returns_404_for_missing_project(self, client):
        resp = await client.get(
            "/api/projects/99999/experiments/99999/judge-reliability"
        )
        assert resp.status_code == 404
        assert "Project not found" in resp.json()["detail"]

    async def test_returns_404_for_missing_experiment(self, client, project_id):
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/99999/judge-reliability"
        )
        assert resp.status_code == 404
        assert "Experiment not found" in resp.json()["detail"]

    async def test_returns_200_with_empty_reliability(
        self, client, project_id, experiment_id
    ):
        """Experiment exists and is completed but has no evaluations to aggregate."""
        resp = await client.get(
            f"/api/projects/{project_id}/experiments/{experiment_id}/judge-reliability"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_id"] == experiment_id
        assert data["evaluators"] == []
        assert data["excluded_indices"] == []
        assert data["overall_reliability"] is None
        assert "threshold" in data


# ---------------------------------------------------------------------------
# TestAnnotateClaim
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAnnotateClaim:
    """POST /api/projects/{p}/experiments/{e}/results/{r}/judge-evaluations/{ev}/claims/{i}/annotate"""

    async def test_returns_404_for_missing_evaluation(
        self, client, project_id, experiment_id, result_id
    ):
        resp = await client.post(
            f"/api/projects/{project_id}/experiments/{experiment_id}"
            f"/results/{result_id}/judge-evaluations/99999/claims/0/annotate",
            json={"status": "accurate"},
        )
        assert resp.status_code == 404
        assert "Evaluation not found" in resp.json()["detail"]
