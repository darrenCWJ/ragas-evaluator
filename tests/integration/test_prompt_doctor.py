"""Integration tests for the prompt-doctor endpoint."""

import json
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
def project(client):
    import uuid

    resp = client.post(
        "/api/projects", json={"name": f"doctor-it-{uuid.uuid4().hex[:8]}", "description": ""}
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _seed_experiment(pid: int) -> int:
    conn = db.init.get_db()
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'dr')", (pid,)
    ).lastrowid
    qids = []
    for q, a, cat in [
        ("What is the refund window?", "30 days.", "typical"),
        ("What is the CEO blood type?", "Not in KB.", "out_of_knowledge_base"),
    ]:
        qids.append(conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, reference_contexts, question_type, persona, category, status) "
            "VALUES (?, ?, ?, '[]', 'uploaded', '', ?, 'approved')",
            (ts, q, a, cat),
        ).lastrowid)
    exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
        "VALUES (?, ?, 'dr-exp', 'gpt-4o-mini', 'completed')",
        (pid, ts),
    ).lastrowid
    conn.execute(
        "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
        "VALUES (?, ?, 'It is 30 days.', '[]', ?, '{}')",
        (exp, qids[0], json.dumps({"faithfulness": 0.9})),
    )
    conn.execute(
        "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
        "VALUES (?, ?, 'The CEO is type O.', '[]', ?, '{}')",
        (exp, qids[1], json.dumps({"refusal_accuracy": 0.0})),
    )
    conn.commit()
    return exp


DOCTOR_REPLY = {
    "content": json.dumps({
        "diagnosis": ["Fabricates answers to out-of-scope questions (CEO blood type example)"],
        "revised_system_prompt": "You are a precise assistant.\n\nWHEN THE ANSWER IS NOT IN THE CONTEXT: decline.",
        "additions": [
            {"type": "guardrail", "text": "WHEN THE ANSWER IS NOT IN THE CONTEXT: decline.",
             "reason": "Fabricated CEO blood type instead of declining"},
        ],
    }),
    "usage": {},
}


class TestPromptDoctor:
    def test_doctor_creates_applyable_suggestions(self, client, project):
        exp = _seed_experiment(project)
        with patch("pipeline.llm.chat_completion", new=AsyncMock(return_value=DOCTOR_REPLY)), \
             patch("app.routes.analyze.chat_completion", new=AsyncMock(return_value=DOCTOR_REPLY), create=True):
            r = client.post(f"/api/projects/{project}/experiments/{exp}/prompt-doctor")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["suggestions_created"] == 2
        assert body["external_agent"] is False
        assert "decline" in body["revised_system_prompt"]
        assert body["diagnosis"]

        s = client.get(f"/api/projects/{project}/experiments/{exp}/suggestions").json()
        prompt_rows = [x for x in s["suggestions"] if x["category"] == "prompt"]
        fields = {x["config_field"] for x in prompt_rows}
        assert fields == {"system_prompt_append", "system_prompt"}
        append_row = next(x for x in prompt_rows if x["config_field"] == "system_prompt_append")
        assert "decline" in append_row["suggested_value"]

    def test_doctor_rerun_replaces_prior_prompt_suggestions(self, client, project):
        exp = _seed_experiment(project)
        with patch("pipeline.llm.chat_completion", new=AsyncMock(return_value=DOCTOR_REPLY)):
            client.post(f"/api/projects/{project}/experiments/{exp}/prompt-doctor")
            client.post(f"/api/projects/{project}/experiments/{exp}/prompt-doctor")
        s = client.get(f"/api/projects/{project}/experiments/{exp}/suggestions").json()
        prompt_rows = [x for x in s["suggestions"] if x["category"] == "prompt"]
        assert len(prompt_rows) == 2  # not 4 — rerun replaced

    def test_incomplete_experiment_409(self, client, project):
        conn = db.init.get_db()
        ts = conn.execute(
            "INSERT INTO test_sets (project_id, name) VALUES (?, 'x')", (project,)
        ).lastrowid
        exp = conn.execute(
            "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
            "VALUES (?, ?, 'running-exp', 'm', 'running')",
            (project, ts),
        ).lastrowid
        conn.commit()
        r = client.post(f"/api/projects/{project}/experiments/{exp}/prompt-doctor")
        assert r.status_code == 409
