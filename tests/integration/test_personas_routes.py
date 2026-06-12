"""Integration tests for persona routes — CRUD, validation, isolation, generation guards.

The full-mode generation path (subprocess + thread machinery) is not exercised;
fast-mode generation is tested with the LLM-backed generator mocked at its
source module so no API calls are made.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import db.init
import main

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def _make_project(client) -> int:
    name = f"personas-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def project(client):
    pid = _make_project(client)
    yield pid
    client.delete(f"/api/projects/{pid}")


@pytest.fixture
def other_project(client):
    pid = _make_project(client)
    yield pid
    client.delete(f"/api/projects/{pid}")


def _create_persona(client, pid: int, name: str = "Support Agent") -> dict:
    r = client.post(
        f"/api/projects/{pid}/personas",
        json={
            "name": name,
            "role_description": "Answers customer support questions.",
            "question_style": "short and direct",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _seed_chunk_config(pid: int, with_chunks: bool) -> int:
    """Insert a chunk config (and optionally one chunk) directly in the DB."""
    conn = db.init.get_db()
    try:
        cc = conn.execute(
            "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, 'cc', 'recursive', '{}')",
            (pid,),
        ).lastrowid
        if with_chunks:
            doc = conn.execute(
                "INSERT INTO documents (project_id, filename, file_type, content) "
                "VALUES (?, 'a.txt', '.txt', 'Refunds take 30 days.')",
                (pid,),
            ).lastrowid
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_config_id, content) VALUES (?, ?, 'Refunds take 30 days.')",
                (doc, cc),
            )
        conn.commit()
        return cc
    except Exception:
        conn.rollback()
        raise


class TestPersonaCrud:
    def test_create_and_list(self, client, project):
        created = _create_persona(client, project)
        assert created["name"] == "Support Agent"
        assert created["question_style"] == "short and direct"

        listed = client.get(f"/api/projects/{project}/personas")
        assert listed.status_code == 200
        personas = listed.json()["personas"]
        assert len(personas) == 1
        assert personas[0]["id"] == created["id"]
        assert personas[0]["role_description"] == "Answers customer support questions."

    def test_bulk_create(self, client, project):
        r = client.post(
            f"/api/projects/{project}/personas/bulk",
            json=[
                {"name": "New Hire", "role_description": "Asks onboarding questions."},
                {"name": "Power User", "role_description": "Asks edge-case questions.",
                 "question_style": "detailed"},
            ],
        )
        assert r.status_code == 201, r.text
        saved = r.json()["personas"]
        assert len(saved) == 2
        assert all(p["id"] for p in saved)

        listed = client.get(f"/api/projects/{project}/personas").json()["personas"]
        assert {p["name"] for p in listed} == {"New Hire", "Power User"}

    def test_update_partial_fields(self, client, project):
        pid = _create_persona(client, project)["id"]
        r = client.put(
            f"/api/projects/{project}/personas/{pid}",
            json={"question_style": "verbose and skeptical"},
        )
        assert r.status_code == 200, r.text

        persona = client.get(f"/api/projects/{project}/personas").json()["personas"][0]
        assert persona["question_style"] == "verbose and skeptical"
        # Unspecified fields untouched
        assert persona["name"] == "Support Agent"

    def test_delete_persona(self, client, project):
        pid = _create_persona(client, project)["id"]
        r = client.delete(f"/api/projects/{project}/personas/{pid}")
        assert r.status_code == 200
        assert client.get(f"/api/projects/{project}/personas").json()["personas"] == []
        # Second delete -> 404
        assert client.delete(f"/api/projects/{project}/personas/{pid}").status_code == 404


class TestValidationAndIsolation:
    def test_unknown_project_404(self, client):
        assert client.get("/api/projects/99999999/personas").status_code == 404
        r = client.post(
            "/api/projects/99999999/personas",
            json={"name": "x", "role_description": "y"},
        )
        assert r.status_code == 404

    def test_create_missing_role_description_422(self, client, project):
        r = client.post(
            f"/api/projects/{project}/personas", json={"name": "incomplete"}
        )
        assert r.status_code == 422

    def test_cross_project_isolation_404(self, client, project, other_project):
        persona_id = _create_persona(client, project)["id"]

        # Other project cannot see, update, or delete it
        assert client.get(
            f"/api/projects/{other_project}/personas"
        ).json()["personas"] == []
        upd = client.put(
            f"/api/projects/{other_project}/personas/{persona_id}",
            json={"name": "hijacked"},
        )
        assert upd.status_code == 404
        dele = client.delete(f"/api/projects/{other_project}/personas/{persona_id}")
        assert dele.status_code == 404


class TestGeneration:
    def test_generate_unknown_chunk_config_404(self, client, project):
        r = client.post(
            f"/api/projects/{project}/generate-personas",
            json={"chunk_config_id": 99999999, "num_personas": 3},
        )
        assert r.status_code == 404

    def test_generate_no_chunks_422(self, client, project):
        cc = _seed_chunk_config(project, with_chunks=False)
        r = client.post(
            f"/api/projects/{project}/generate-personas",
            json={"chunk_config_id": cc, "num_personas": 3},
        )
        assert r.status_code == 422

    def test_generate_fast_mode_with_mocked_llm(self, client, project):
        cc = _seed_chunk_config(project, with_chunks=True)
        fake_personas = [
            {"name": "Customer", "role_description": "Asks about refunds.",
             "question_style": "casual"},
        ]
        # Patch the source module: the route imports the function at call time.
        with patch(
            "evaluation.metrics.testgen.generate_personas_fast",
            return_value=fake_personas,
        ) as mocked:
            r = client.post(
                f"/api/projects/{project}/generate-personas",
                json={"chunk_config_id": cc, "num_personas": 1, "mode": "fast"},
            )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "completed", "personas": fake_personas}
        assert mocked.call_count == 1
        assert mocked.call_args.kwargs["num_personas"] == 1

    def test_generation_status_without_task_404(self, client, project):
        r = client.get(f"/api/projects/{project}/generate-personas/status")
        assert r.status_code == 404
