"""Integration test: the diagnose -> apply -> verify loop on suggestions."""

import json

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
        "/api/projects", json={"name": f"outcome-it-{uuid.uuid4().hex[:8]}", "description": ""}
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _seed_pair(pid: int, applied_status: str = "completed") -> dict:
    """Baseline experiment + applied follow-up sharing the same questions."""
    conn = db.init.get_db()
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'loop')", (pid,)
    ).lastrowid
    qids = [
        conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, reference_contexts, question_type, persona, status) "
            "VALUES (?, ?, 'ref', '[]', 'uploaded', '', 'approved')",
            (ts, f"Q{i}?"),
        ).lastrowid
        for i in range(6)
    ]
    base_exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
        "VALUES (?, ?, 'base', 'm', 'completed')",
        (pid, ts),
    ).lastrowid
    applied_exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status, baseline_experiment_id) "
        "VALUES (?, ?, 'iter-1', 'm', ?, ?)",
        (pid, ts, applied_status, base_exp),
    ).lastrowid
    for qid in qids:
        conn.execute(
            "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json) "
            "VALUES (?, ?, 'r', '[]', ?)",
            (base_exp, qid, json.dumps({"faithfulness": 0.5})),
        )
        if applied_status == "completed":
            conn.execute(
                "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json) "
                "VALUES (?, ?, 'r', '[]', ?)",
                (applied_exp, qid, json.dumps({"faithfulness": 0.85})),
            )
    sid = conn.execute(
        "INSERT INTO suggestions (experiment_id, category, signal, suggestion, priority, config_field, suggested_value, implemented, applied_experiment_id) "
        "VALUES (?, 'guardrail', 'faithfulness avg 0.50', 'add grounding', 'high', 'system_prompt_append', 'GROUNDING', TRUE, ?)",
        (base_exp, applied_exp),
    ).lastrowid
    conn.commit()
    return {"base_exp": base_exp, "applied_exp": applied_exp, "suggestion_id": sid}


class TestSuggestionOutcomes:
    def test_completed_followup_yields_improved_verdict(self, client, project):
        seeded = _seed_pair(project)
        r = client.get(
            f"/api/projects/{project}/experiments/{seeded['base_exp']}/suggestions"
        )
        assert r.status_code == 200, r.text
        s = r.json()["suggestions"][0]
        outcome = s["outcome"]
        assert outcome["status"] == "evaluated"
        assert outcome["overall"] == "improved"
        assert outcome["metrics"]["faithfulness"]["verdict"] == "improved"
        assert outcome["compared_questions"] == 6

        # Cached on second read (row now has outcome_json persisted)
        conn = db.init.get_db()
        cached = conn.execute(
            "SELECT outcome_json FROM suggestions WHERE id = ?",
            (seeded["suggestion_id"],),
        ).fetchone()
        assert cached["outcome_json"] is not None

    def test_running_followup_reports_pending(self, client, project):
        seeded = _seed_pair(project, applied_status="running")
        r = client.get(
            f"/api/projects/{project}/experiments/{seeded['base_exp']}/suggestions"
        )
        outcome = r.json()["suggestions"][0]["outcome"]
        assert outcome["status"] == "pending"

    def test_unapplied_suggestion_has_no_outcome(self, client, project):
        seeded = _seed_pair(project)
        conn = db.init.get_db()
        conn.execute(
            "INSERT INTO suggestions (experiment_id, category, signal, suggestion, priority) "
            "VALUES (?, 'retrieval', 'sig', 'do x', 'low')",
            (seeded["base_exp"],),
        )
        conn.commit()
        r = client.get(
            f"/api/projects/{project}/experiments/{seeded['base_exp']}/suggestions"
        )
        unapplied = [s for s in r.json()["suggestions"] if s["category"] == "retrieval"]
        assert unapplied[0]["outcome"] is None
