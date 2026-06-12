"""Integration tests for log import and hard-case mining routes."""

import json
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
def project(client):
    name = f"mine-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


class TestImportLogs:
    def test_txt_import_dedupes_and_counts(self, client, project):
        logs = b"How do I reset my password?\nhi\nHow do I reset my password?\nWhat plans exist?\n"
        resp = client.post(
            f"/api/projects/{project}/test-sets/import-logs",
            files={"file": ("queries.txt", logs, "text/plain")},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["imported"] == 2
        assert body["skipped"] == {"trivial": 1, "duplicate": 1}

        conn = db.init.get_db()
        questions = conn.execute(
            "SELECT * FROM test_questions WHERE test_set_id = ?", (body["test_set_id"],)
        ).fetchall()
        assert len(questions) == 2
        assert all(q["reference_answer"] == "" for q in questions)
        assert all(q["status"] == "approved" for q in questions)
        assert all(q["question_type"] == "log_import" for q in questions)

    def test_csv_auto_detects_query_column(self, client, project):
        csv = b"timestamp,query\n2026-01-01,How does billing work this month?\n2026-01-02,Where is my invoice document?\n"
        resp = client.post(
            f"/api/projects/{project}/test-sets/import-logs",
            files={"file": ("logs.csv", csv, "text/csv")},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["imported"] == 2

    def test_csv_unknown_column_rejected(self, client, project):
        csv = b"timestamp,utterance\n2026-01-01,How does billing work?\n"
        resp = client.post(
            f"/api/projects/{project}/test-sets/import-logs",
            files={"file": ("logs.csv", csv, "text/csv")},
        )
        assert resp.status_code == 422
        assert "question_column" in resp.text

    def test_all_trivial_rejected(self, client, project):
        resp = client.post(
            f"/api/projects/{project}/test-sets/import-logs",
            files={"file": ("queries.txt", b"hi\nok\n\n", "text/plain")},
        )
        assert resp.status_code == 422


@pytest.fixture
def completed_experiment(project):
    conn = db.init.get_db()
    try:
        ts = conn.execute(
            "INSERT INTO test_sets (project_id, name) VALUES (?, 'mine-set')", (project,)
        ).lastrowid
        qid = conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, reference_contexts, status) "
            "VALUES (?, 'why is the sky blue?', 'rayleigh scattering', '[]', 'approved')",
            (ts,),
        ).lastrowid
        exp = conn.execute(
            "INSERT INTO experiments (project_id, test_set_id, name, model, status) VALUES (?, ?, 'mine-exp', 'm', 'completed')",
            (project, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
            "VALUES (?, ?, 'r', '[]', ?, '{}')",
            (exp, qid, json.dumps({"bleu_score": 0.1})),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"pid": project, "exp": exp}


class TestMineHardCases:
    def test_mines_variants(self, client, completed_experiment):
        llm = AsyncMock(return_value={
            "content": "what makes the sky look blue?\nexplain the sky's colour",
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        })
        with patch("app.services.case_mining.chat_completion", llm):
            resp = client.post(
                f"/api/projects/{completed_experiment['pid']}/experiments/{completed_experiment['exp']}/mine-hard-cases",
                json={"threshold": 0.5, "variants_per_question": 2},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["hard_cases"] == 1
        assert body["variants_created"] == 2

    def test_no_hard_cases_409(self, client, completed_experiment):
        resp = client.post(
            f"/api/projects/{completed_experiment['pid']}/experiments/{completed_experiment['exp']}/mine-hard-cases",
            json={"threshold": 0.05},
        )
        assert resp.status_code == 409

    def test_requires_completed_experiment(self, client, completed_experiment):
        conn = db.init.get_db()
        conn.execute(
            "UPDATE experiments SET status = 'pending' WHERE id = ?",
            (completed_experiment["exp"],),
        )
        conn.commit()
        resp = client.post(
            f"/api/projects/{completed_experiment['pid']}/experiments/{completed_experiment['exp']}/mine-hard-cases",
            json={},
        )
        assert resp.status_code == 409
