"""Integration tests for the insights routes (quality audit, coverage, breakdown)."""

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

    name = f"insights-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _seed(pid: int) -> dict:
    """Seed a document, chunks, test set with provenance, and an experiment.

    Wrapped so a mid-seed failure rolls back instead of wedging the shared
    SQLite connection with an open write transaction.
    """
    conn = db.init.get_db()
    try:
        return _seed_inner(conn, pid)
    except Exception:
        conn.rollback()
        raise


def _seed_inner(conn, pid: int) -> dict:
    doc = conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content) VALUES (?, 'a.txt', '.txt', 'Refunds: 30 days. Passwords: settings page.')",
        (pid,),
    ).lastrowid
    doc2 = conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content) VALUES (?, 'never-tested.txt', '.txt', 'Shipping takes 5 days.')",
        (pid,),
    ).lastrowid
    cc = conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, 'cc', 'recursive', '{}')",
        (pid,),
    ).lastrowid
    chunk1 = conn.execute(
        "INSERT INTO chunks (document_id, chunk_config_id, content) VALUES (?, ?, 'Refunds: 30 days.')",
        (doc, cc),
    ).lastrowid
    conn.execute(
        "INSERT INTO chunks (document_id, chunk_config_id, content) VALUES (?, ?, 'Shipping takes 5 days.')",
        (doc2, cc),
    )

    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'seeded')", (pid,)
    ).lastrowid
    q1 = conn.execute(
        """INSERT INTO test_questions
           (test_set_id, question, reference_answer, reference_contexts, question_type, persona, category, status, metadata_json)
           VALUES (?, 'What is the refund window for purchases?', '30 days.', ?, 'single_hop_specific_query_synthesizer', '', 'typical', 'approved', ?)""",
        (ts, json.dumps(["Refunds: 30 days."]),
         json.dumps({"source_chunk_ids": [chunk1], "source_document_ids": [doc]})),
    ).lastrowid
    q2 = conn.execute(
        """INSERT INTO test_questions
           (test_set_id, question, reference_answer, reference_contexts, question_type, persona, category, status, metadata_json)
           VALUES (?, 'What is the CEO shoe size mentioned in the docs?', 'Not covered by the knowledge base.', '[]', 'out_of_knowledge_base', '', 'out_of_knowledge_base', 'approved', ?)""",
        (ts, json.dumps({"expected_behavior": "refusal"})),
    ).lastrowid

    exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
        "VALUES (?, ?, 'e1', 'gpt-4o-mini', 'completed')",
        (pid, ts),
    ).lastrowid
    conn.execute(
        "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
        "VALUES (?, ?, 'The refund window is 30 days.', '[]', ?, '{}')",
        (exp, q1, json.dumps({"faithfulness": 0.9, "answer_relevancy": 0.8})),
    )
    conn.execute(
        "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
        "VALUES (?, ?, 'The CEO wears size 42.', '[]', ?, '{}')",
        (exp, q2, json.dumps({"refusal_accuracy": 0.0, "answer_relevancy": 0.3})),
    )
    conn.commit()
    return {"test_set_id": ts, "experiment_id": exp, "doc2": doc2}


class TestQualityAudit:
    def test_deterministic_audit_persists_and_summarizes(self, client, project):
        seeded = _seed(project)
        r = client.post(
            f"/api/projects/{project}/test-sets/{seeded['test_set_id']}/quality-audit",
            json={"use_llm": False},
        )
        assert r.status_code == 200, r.text
        summary = r.json()
        assert summary["audited"] == 2
        assert summary["avg_score"] is not None

        # Quality assessment persisted into question metadata
        qs = client.get(
            f"/api/projects/{project}/test-sets/{seeded['test_set_id']}/questions"
        )
        if qs.status_code == 200:
            data = qs.json()
            items = data if isinstance(data, list) else data.get("questions", [])
            with_quality = [
                q for q in items
                if (q.get("metadata") or {}).get("quality") is not None
            ]
            assert len(with_quality) == 2

    def test_empty_set_409(self, client, project):
        conn = db.init.get_db()
        ts = conn.execute(
            "INSERT INTO test_sets (project_id, name) VALUES (?, 'empty')", (project,)
        ).lastrowid
        conn.commit()
        r = client.post(
            f"/api/projects/{project}/test-sets/{ts}/quality-audit", json={"use_llm": False}
        )
        assert r.status_code == 409


class TestCoverage:
    def test_coverage_report(self, client, project):
        seeded = _seed(project)
        r = client.get(
            f"/api/projects/{project}/test-sets/{seeded['test_set_id']}/coverage"
        )
        assert r.status_code == 200, r.text
        cov = r.json()
        assert cov["total_questions"] == 2
        assert cov["covered_documents"] == 1
        assert "never-tested.txt" in cov["uncovered_documents"]
        assert cov["covered_chunks"] == 1
        assert cov["chunk_coverage"] == 0.5


class TestBreakdown:
    def test_breakdown_groups_by_category(self, client, project):
        seeded = _seed(project)
        r = client.get(
            f"/api/projects/{project}/experiments/{seeded['experiment_id']}/breakdown"
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c for c in r.json()["categories"]}
        assert set(cats) == {"typical", "out_of_knowledge_base"}
        assert cats["typical"]["metrics"]["faithfulness"] == 0.9
        assert cats["out_of_knowledge_base"]["metrics"]["refusal_accuracy"] == 0.0
        # Weakest category sorts first
        assert r.json()["categories"][0]["category"] == "out_of_knowledge_base"
        weakest = cats["out_of_knowledge_base"]["weakest_questions"]
        assert weakest and "shoe size" in weakest[0]["question"]


class TestExternalTestSetUpload:
    """External scenario: test set uploaded via API, agent called via API."""

    def test_upload_with_category_column_tags_refusal(self, client, project):
        csv_content = (
            "question,answer,category\n"
            "What is the refund window?,30 days.,typical\n"
            "What is the CEO's blood type?,Not in the knowledge base.,out_of_knowledge_base\n"
            "Who won the 2030 World Cup?,I cannot answer that.,Unanswerable\n"
        )
        r = client.post(
            f"/api/projects/{project}/test-sets/upload",
            files={"file": ("external.csv", csv_content, "text/csv")},
            data={
                "question_column": "question",
                "answer_column": "answer",
                "category_column": "category",
                "name": "external-set",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        questions = body.get("questions") or body.get("inserted") or []
        by_q = {q["question"]: q for q in questions}

        assert by_q["What is the refund window?"]["category"] == "typical"
        assert (by_q["What is the refund window?"]["metadata"] or {}).get("expected_behavior") is None

        # Both refusal-style category values (any casing) get the refusal tag
        ceo = by_q["What is the CEO's blood type?"]
        assert ceo["category"] == "out_of_knowledge_base"
        assert ceo["metadata"]["expected_behavior"] == "refusal"
        cup = by_q["Who won the 2030 World Cup?"]
        assert cup["metadata"]["expected_behavior"] == "refusal"

    def test_unknown_category_column_rejected(self, client, project):
        csv_content = "question,answer\nQ1?,A1.\n"
        r = client.post(
            f"/api/projects/{project}/test-sets/upload",
            files={"file": ("x.csv", csv_content, "text/csv")},
            data={
                "question_column": "question",
                "answer_column": "answer",
                "category_column": "nonexistent",
            },
        )
        assert r.status_code == 422
        assert "category_column" in r.json()["detail"]

    def test_breakdown_works_for_uploaded_categories(self, client, project):
        """Full external loop: uploaded set -> experiment rows -> breakdown."""
        csv_content = (
            "question,answer,category\n"
            "What is the refund window?,30 days.,typical\n"
            "What is the CEO's blood type?,Not available.,out_of_knowledge_base\n"
        )
        r = client.post(
            f"/api/projects/{project}/test-sets/upload",
            files={"file": ("external.csv", csv_content, "text/csv")},
            data={
                "question_column": "question",
                "answer_column": "answer",
                "category_column": "category",
            },
        )
        ts_id = r.json()["id"]

        conn = db.init.get_db()
        q_rows = conn.execute(
            "SELECT id, category FROM test_questions WHERE test_set_id = ?", (ts_id,)
        ).fetchall()
        exp = conn.execute(
            "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
            "VALUES (?, ?, 'ext', 'bot', 'completed')",
            (project, ts_id),
        ).lastrowid
        for q in q_rows:
            metrics = (
                {"refusal_accuracy": 1.0}
                if q["category"] == "out_of_knowledge_base"
                else {"faithfulness": 0.8}
            )
            conn.execute(
                "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
                "VALUES (?, ?, 'resp', '[]', ?, '{}')",
                (exp, q["id"], json.dumps(metrics)),
            )
        conn.commit()

        bd = client.get(f"/api/projects/{project}/experiments/{exp}/breakdown")
        assert bd.status_code == 200, bd.text
        cats = {c["category"]: c for c in bd.json()["categories"]}
        assert set(cats) == {"typical", "out_of_knowledge_base"}
        assert cats["out_of_knowledge_base"]["metrics"]["refusal_accuracy"] == 1.0
