"""Integration tests for analyze routes — suggestion generation, update, apply, batch apply.

Only the rule-based suggestion engine is exercised (no LLM calls), so no
mocking is needed: seeded metrics deterministically produce exactly two
suggestions (a top_k retrieval tweak and a grounding guardrail).
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

import db.init
import main

pytestmark = pytest.mark.integration

# faithfulness 0.5 -> system_prompt_append guardrail; context_recall 0.5 -> top_k "+5".
# answer_relevancy 0.9 is healthy. Identical metrics across questions keep the
# variance-based chunking rule quiet; a single category keeps category rules quiet.
SEED_METRICS = {"faithfulness": 0.5, "context_recall": 0.5, "answer_relevancy": 0.9}


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def project(client):
    name = f"analyze-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _seed(pid: int, *, status: str = "completed", with_rag_config: bool = True,
          with_results: bool = True) -> dict:
    """Seed chunk/embedding/rag configs, a test set, an experiment, and results.

    Wrapped so a mid-seed failure rolls back instead of wedging the shared
    SQLite connection with an open write transaction.
    """
    conn = db.init.get_db()
    try:
        return _seed_inner(conn, pid, status, with_rag_config, with_results)
    except Exception:
        conn.rollback()
        raise


def _seed_inner(conn, pid: int, status: str, with_rag_config: bool, with_results: bool) -> dict:
    cc = conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, 'cc', 'recursive', '{}')",
        (pid,),
    ).lastrowid
    ec = conn.execute(
        "INSERT INTO embedding_configs (project_id, name, type, model_name) "
        "VALUES (?, 'ec', 'openai', 'text-embedding-3-small')",
        (pid,),
    ).lastrowid

    rag_config_id = None
    if with_rag_config:
        rag_config_id = conn.execute(
            "INSERT INTO rag_configs "
            "(project_id, name, embedding_config_id, chunk_config_id, search_type, "
            " llm_model, top_k, system_prompt, response_mode, max_steps) "
            "VALUES (?, 'baseline-config', ?, ?, 'dense', 'gpt-4o-mini', 5, "
            "'Answer using the provided context.', 'single_shot', 3)",
            (pid, ec, cc),
        ).lastrowid

    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'analyze-set')", (pid,)
    ).lastrowid
    question_ids = []
    for i in range(5):
        qid = conn.execute(
            """INSERT INTO test_questions
               (test_set_id, question, reference_answer, reference_contexts, question_type, persona, category, status)
               VALUES (?, ?, ?, '[]', 'uploaded', '', 'typical', 'approved')""",
            (ts, f"Question {i}?", f"Answer {i}."),
        ).lastrowid
        question_ids.append(qid)

    exp = conn.execute(
        "INSERT INTO experiments "
        "(project_id, test_set_id, name, model, rag_config_id, status) "
        "VALUES (?, ?, 'baseline-exp', 'gpt-4o-mini', ?, ?)",
        (pid, ts, rag_config_id, status),
    ).lastrowid

    if with_results:
        for qid in question_ids:
            conn.execute(
                "INSERT INTO experiment_results "
                "(experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
                "VALUES (?, ?, 'resp', '[]', ?, '{}')",
                (exp, qid, json.dumps(SEED_METRICS)),
            )
    conn.commit()
    return {
        "experiment_id": exp,
        "test_set_id": ts,
        "rag_config_id": rag_config_id,
        "chunk_config_id": cc,
        "embedding_config_id": ec,
    }


def _generate(client, pid: int, exp_id: int) -> list[dict]:
    r = client.post(f"/api/projects/{pid}/experiments/{exp_id}/suggestions/generate")
    assert r.status_code == 200, r.text
    return r.json()["suggestions"]


def _by_field(suggestions: list[dict], config_field: str) -> dict:
    matches = [s for s in suggestions if s["config_field"] == config_field]
    assert matches, f"no suggestion with config_field={config_field}: {suggestions}"
    return matches[0]


class TestGenerateSuggestions:
    def test_rule_based_generation_persists(self, client, project):
        seeded = _seed(project)
        suggestions = _generate(client, project, seeded["experiment_id"])

        assert len(suggestions) == 2
        top_k = _by_field(suggestions, "top_k")
        assert top_k["category"] == "retrieval"
        assert top_k["suggested_value"] == "+5"
        guardrail = _by_field(suggestions, "system_prompt_append")
        assert guardrail["category"] == "guardrail"
        assert "GROUNDING RULES" in guardrail["suggested_value"]
        assert all(not s["implemented"] for s in suggestions)

        # Regeneration replaces rather than accumulates
        again = _generate(client, project, seeded["experiment_id"])
        assert len(again) == 2

    def test_incomplete_experiment_409(self, client, project):
        seeded = _seed(project, status="running")
        r = client.post(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions/generate"
        )
        assert r.status_code == 409

    def test_no_results_409(self, client, project):
        seeded = _seed(project, with_results=False)
        r = client.post(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions/generate"
        )
        assert r.status_code == 409

    def test_unknown_experiment_404(self, client, project):
        r = client.post(
            f"/api/projects/{project}/experiments/99999999/suggestions/generate"
        )
        assert r.status_code == 404


class TestListAndUpdateSuggestions:
    def test_list_suggestions(self, client, project):
        seeded = _seed(project)
        _generate(client, project, seeded["experiment_id"])

        r = client.get(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions"
        )
        assert r.status_code == 200, r.text
        listed = r.json()["suggestions"]
        assert len(listed) == 2
        # Not yet applied -> no outcome
        assert all(s["outcome"] is None for s in listed)

    def test_patch_implemented_flag(self, client, project):
        seeded = _seed(project)
        sid = _generate(client, project, seeded["experiment_id"])[0]["id"]

        r = client.patch(
            f"/api/projects/{project}/suggestions/{sid}", json={"implemented": True}
        )
        assert r.status_code == 200, r.text
        assert r.json()["implemented"]

        r2 = client.patch(
            f"/api/projects/{project}/suggestions/{sid}", json={"implemented": False}
        )
        assert not r2.json()["implemented"]

    def test_patch_cross_project_isolation_404(self, client, project):
        seeded = _seed(project)
        sid = _generate(client, project, seeded["experiment_id"])[0]["id"]
        r = client.patch(
            f"/api/projects/99999999/suggestions/{sid}", json={"implemented": True}
        )
        assert r.status_code == 404


class TestApplySuggestion:
    def test_apply_top_k_creates_config_and_pending_experiment(self, client, project):
        seeded = _seed(project)
        suggestions = _generate(client, project, seeded["experiment_id"])
        sid = _by_field(suggestions, "top_k")["id"]

        r = client.post(f"/api/projects/{project}/suggestions/{sid}/apply", json={})
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["changes"]["top_k"] == {"old": 5, "new": 10}
        assert "iteration 1" in body["new_rag_config"]["name"]

        new_exp = body["new_experiment"]
        assert new_exp["status"] == "pending"
        assert new_exp["baseline_experiment_id"] == seeded["experiment_id"]
        assert new_exp["rag_config_id"] == body["new_rag_config"]["id"]
        assert new_exp["test_set_id"] == seeded["test_set_id"]

        assert body["suggestion"]["implemented"]
        assert body["suggestion"]["applied_experiment_id"] == new_exp["id"]

        # New config row carries the bumped top_k
        conn = db.init.get_db()
        cfg = conn.execute(
            "SELECT top_k FROM rag_configs WHERE id = ?",
            (body["new_rag_config"]["id"],),
        ).fetchone()
        assert cfg["top_k"] == 10

        # Outcome shows pending until the follow-up experiment completes
        listed = client.get(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions"
        ).json()["suggestions"]
        applied = next(s for s in listed if s["id"] == sid)
        assert applied["outcome"]["status"] == "pending"

    def test_apply_system_prompt_append(self, client, project):
        seeded = _seed(project)
        suggestions = _generate(client, project, seeded["experiment_id"])
        sid = _by_field(suggestions, "system_prompt_append")["id"]

        r = client.post(f"/api/projects/{project}/suggestions/{sid}/apply", json={})
        assert r.status_code == 200, r.text
        change = r.json()["changes"]["system_prompt"]
        assert change["old"] == "Answer using the provided context."
        assert change["new"].startswith("Answer using the provided context.")
        assert "GROUNDING RULES" in change["new"]

        conn = db.init.get_db()
        cfg = conn.execute(
            "SELECT system_prompt FROM rag_configs WHERE id = ?",
            (r.json()["new_rag_config"]["id"],),
        ).fetchone()
        assert "GROUNDING RULES" in cfg["system_prompt"]

    def test_apply_already_implemented_409(self, client, project):
        seeded = _seed(project)
        sid = _by_field(
            _generate(client, project, seeded["experiment_id"]), "top_k"
        )["id"]
        assert client.post(
            f"/api/projects/{project}/suggestions/{sid}/apply", json={}
        ).status_code == 200
        r = client.post(f"/api/projects/{project}/suggestions/{sid}/apply", json={})
        assert r.status_code == 409

    def test_apply_no_config_mapping_400(self, client, project):
        seeded = _seed(project)
        conn = db.init.get_db()
        sid = conn.execute(
            "INSERT INTO suggestions (experiment_id, category, signal, suggestion, priority) "
            "VALUES (?, 'embedding', 'manual', 'Needs human review', 'medium')",
            (seeded["experiment_id"],),
        ).lastrowid
        conn.commit()

        r = client.post(f"/api/projects/{project}/suggestions/{sid}/apply", json={})
        assert r.status_code == 400
        assert "manual review" in r.json()["detail"]

    def test_apply_experiment_without_rag_config_409(self, client, project):
        seeded = _seed(project, with_rag_config=False)
        conn = db.init.get_db()
        sid = conn.execute(
            "INSERT INTO suggestions "
            "(experiment_id, category, signal, suggestion, priority, config_field, suggested_value) "
            "VALUES (?, 'retrieval', 'sig', 'bump top_k', 'high', 'top_k', '+5')",
            (seeded["experiment_id"],),
        ).lastrowid
        conn.commit()

        r = client.post(f"/api/projects/{project}/suggestions/{sid}/apply", json={})
        assert r.status_code == 409
        assert "no RAG config" in r.json()["detail"]

    def test_apply_unknown_suggestion_404(self, client, project):
        r = client.post(f"/api/projects/{project}/suggestions/99999999/apply", json={})
        assert r.status_code == 404


class TestBatchApply:
    def test_batch_apply_combines_changes_into_one_experiment(self, client, project):
        seeded = _seed(project)
        suggestions = _generate(client, project, seeded["experiment_id"])
        items = [{"suggestion_id": s["id"]} for s in suggestions]

        r = client.post(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions/apply-batch",
            json={"items": items, "experiment_name": "combined fix"},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert set(body["changes"]) == {"top_k", "system_prompt"}
        assert body["changes"]["top_k"]["new"] == 10
        assert "GROUNDING RULES" in body["changes"]["system_prompt"]["new"]

        assert body["new_experiment"]["name"] == "combined fix"
        assert body["new_experiment"]["status"] == "pending"
        assert body["new_experiment"]["baseline_experiment_id"] == seeded["experiment_id"]
        assert all(s["implemented"] for s in body["suggestions"])

        # Single new config got both changes
        conn = db.init.get_db()
        cfg = conn.execute(
            "SELECT top_k, system_prompt FROM rag_configs WHERE id = ?",
            (body["new_rag_config"]["id"],),
        ).fetchone()
        assert cfg["top_k"] == 10
        assert "GROUNDING RULES" in cfg["system_prompt"]

    def test_batch_apply_empty_items_400(self, client, project):
        seeded = _seed(project)
        r = client.post(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions/apply-batch",
            json={"items": []},
        )
        assert r.status_code == 400

    def test_batch_apply_missing_suggestion_404(self, client, project):
        seeded = _seed(project)
        r = client.post(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions/apply-batch",
            json={"items": [{"suggestion_id": 99999999}]},
        )
        assert r.status_code == 404

    def test_batch_apply_already_implemented_409(self, client, project):
        seeded = _seed(project)
        suggestions = _generate(client, project, seeded["experiment_id"])
        sid = _by_field(suggestions, "top_k")["id"]
        client.post(f"/api/projects/{project}/suggestions/{sid}/apply", json={})

        r = client.post(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/suggestions/apply-batch",
            json={"items": [{"suggestion_id": sid}]},
        )
        assert r.status_code == 409
        assert "already applied" in r.json()["detail"]
