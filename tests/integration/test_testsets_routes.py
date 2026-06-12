"""Integration tests for test set routes — upload preview/confirm, annotation, bulk actions, CRUD.

Generation/KG endpoints (background threads + subprocesses) are deliberately
NOT exercised here; only their synchronous validation guards are tested.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import db.init
import main

pytestmark = pytest.mark.integration

CSV_CONTENT = (
    "question,answer,category\n"
    "What is the refund window?,30 days.,typical\n"
    "How do I reset my password?,Settings page.,typical\n"
    "What is the CEO's blood type?,Not in the knowledge base.,out_of_knowledge_base\n"
)


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def project(client):
    name = f"testsets-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _upload(client, pid: int, csv: str = CSV_CONTENT, **form_overrides):
    """Upload a test set CSV with column mapping; returns the response."""
    data = {
        "question_column": "question",
        "answer_column": "answer",
        "category_column": "category",
        "name": "uploaded-set",
    }
    data.update(form_overrides)
    return client.post(
        f"/api/projects/{pid}/test-sets/upload",
        files={"file": ("qa.csv", csv, "text/csv")},
        data={k: v for k, v in data.items() if v is not None},
    )


def _seed_experiment_for(pid: int, test_set_id: int) -> int:
    """Insert an experiment row referencing the test set (try/rollback wrapped)."""
    conn = db.init.get_db()
    try:
        exp = conn.execute(
            "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
            "VALUES (?, ?, 'ref-exp', 'gpt-4o-mini', 'completed')",
            (pid, test_set_id),
        ).lastrowid
        conn.commit()
        return exp
    except Exception:
        conn.rollback()
        raise


class TestUploadPreview:
    def test_preview_returns_columns_and_sample_rows(self, client, project):
        r = client.post(
            f"/api/projects/{project}/test-sets/upload/preview",
            files={"file": ("qa.csv", CSV_CONTENT, "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["filename"] == "qa.csv"
        assert body["total_rows"] == 3
        assert body["columns"] == ["question", "answer", "category"]
        assert len(body["preview"]) == 3
        assert body["preview"][0]["question"] == "What is the refund window?"

    def test_preview_empty_file_422(self, client, project):
        r = client.post(
            f"/api/projects/{project}/test-sets/upload/preview",
            files={"file": ("empty.csv", "", "text/csv")},
        )
        assert r.status_code == 422
        assert "empty" in r.json()["detail"].lower()

    def test_preview_unknown_project_404(self, client):
        r = client.post(
            "/api/projects/99999999/test-sets/upload/preview",
            files={"file": ("qa.csv", CSV_CONTENT, "text/csv")},
        )
        assert r.status_code == 404


class TestUploadConfirm:
    def test_upload_with_category_mapping_creates_questions(self, client, project):
        r = _upload(client, project)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "uploaded-set"
        assert body["question_count"] == 3

        by_q = {q["question"]: q for q in body["questions"]}
        assert by_q["What is the refund window?"]["category"] == "typical"
        assert by_q["What is the refund window?"]["status"] == "pending"
        # Refusal-style category gets the expected_behavior tag
        ookb = by_q["What is the CEO's blood type?"]
        assert ookb["category"] == "out_of_knowledge_base"
        assert ookb["metadata"]["expected_behavior"] == "refusal"

    def test_upload_unknown_question_column_422(self, client, project):
        r = _upload(client, project, question_column="nonexistent")
        assert r.status_code == 422
        assert "nonexistent" in r.json()["detail"]

    def test_upload_empty_answer_cell_422(self, client, project):
        csv = "question,answer,category\nQ1?,,typical\n"
        r = _upload(client, project, csv=csv)
        assert r.status_code == 422
        assert "Row 1" in r.json()["detail"]


class TestCreateTestSetGuards:
    """Synchronous validation guards of the generation endpoint (no threads spawned)."""

    def test_create_without_chunk_config_422(self, client, project):
        r = client.post(f"/api/projects/{project}/test-sets", json={})
        assert r.status_code == 422
        assert "chunk_config_id" in r.json()["detail"]

    def test_create_unknown_chunk_config_404(self, client, project):
        r = client.post(
            f"/api/projects/{project}/test-sets", json={"chunk_config_id": 99999999}
        )
        assert r.status_code == 404

    def test_create_unknown_project_404(self, client):
        r = client.post("/api/projects/99999999/test-sets", json={})
        assert r.status_code == 404


class TestQuestionListing:
    def test_list_test_sets_includes_status_counts(self, client, project):
        _upload(client, project)
        r = client.get(f"/api/projects/{project}/test-sets")
        assert r.status_code == 200, r.text
        sets = r.json()["test_sets"]
        assert len(sets) == 1
        ts = sets[0]
        assert ts["total_questions"] == 3
        assert ts["pending_count"] == 3
        assert ts["approved_count"] == 0
        assert ts["generation_config"]["source"] == "upload"

    def test_list_questions_with_status_filter(self, client, project):
        ts_id = _upload(client, project).json()["id"]

        all_q = client.get(f"/api/projects/{project}/test-sets/{ts_id}/questions")
        assert all_q.status_code == 200
        questions = all_q.json()["questions"]
        assert len(questions) == 3
        assert all(q["status"] == "pending" for q in questions)

        approved = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/questions",
            params={"status": "approved"},
        )
        assert approved.status_code == 200
        assert approved.json()["questions"] == []

    def test_list_questions_invalid_status_422(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        r = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/questions",
            params={"status": "bogus"},
        )
        assert r.status_code == 422

    def test_list_questions_unknown_test_set_404(self, client, project):
        r = client.get(f"/api/projects/{project}/test-sets/99999999/questions")
        assert r.status_code == 404


class TestAnnotation:
    def test_approve_and_reject_question(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        qid = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/questions"
        ).json()["questions"][0]["id"]

        r = client.patch(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/{qid}",
            json={"status": "approved"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        assert r.json()["reviewed_at"] is not None

        r2 = client.patch(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/{qid}",
            json={"status": "rejected", "user_notes": "off-topic"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "rejected"
        assert r2.json()["user_notes"] == "off-topic"

    def test_edit_requires_user_edited_answer(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        qid = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/questions"
        ).json()["questions"][0]["id"]

        missing = client.patch(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/{qid}",
            json={"status": "edited"},
        )
        assert missing.status_code == 422

        edited = client.patch(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/{qid}",
            json={
                "status": "edited",
                "user_edited_answer": "Exactly 30 calendar days.",
                "user_edited_contexts": ["Refund policy: 30 days."],
            },
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["status"] == "edited"
        assert body["user_edited_answer"] == "Exactly 30 calendar days."
        assert body["user_edited_contexts"] == ["Refund policy: 30 days."]

    def test_invalid_annotation_status_422(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        qid = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/questions"
        ).json()["questions"][0]["id"]
        r = client.patch(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/{qid}",
            json={"status": "pending"},  # not a valid annotation status
        )
        assert r.status_code == 422

    def test_annotate_question_not_in_set_404(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        r = client.patch(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/99999999",
            json={"status": "approved"},
        )
        assert r.status_code == 404


class TestBulkActions:
    def test_bulk_approve_specific_ids(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        ids = [
            q["id"]
            for q in client.get(
                f"/api/projects/{project}/test-sets/{ts_id}/questions"
            ).json()["questions"]
        ]
        r = client.post(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/bulk",
            json={"action": "approve", "question_ids": ids[:2]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated_count"] == 2

        summary = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/summary"
        ).json()
        assert summary["approved"] == 2
        assert summary["pending"] == 1

    def test_bulk_approve_invalid_ids_422(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        r = client.post(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/bulk",
            json={"action": "approve", "question_ids": [99999999]},
        )
        assert r.status_code == 422

    def test_bulk_approve_requires_ids(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        r = client.post(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/bulk",
            json={"action": "approve", "question_ids": []},
        )
        assert r.status_code == 422

    def test_bulk_approve_all_updates_only_pending(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        ids = [
            q["id"]
            for q in client.get(
                f"/api/projects/{project}/test-sets/{ts_id}/questions"
            ).json()["questions"]
        ]
        # Reject one first; approve_all must not touch it
        client.post(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/bulk",
            json={"action": "reject", "question_ids": [ids[0]]},
        )
        r = client.post(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/bulk",
            json={"action": "approve_all"},
        )
        assert r.status_code == 200
        assert r.json()["updated_count"] == 2

        summary = client.get(
            f"/api/projects/{project}/test-sets/{ts_id}/summary"
        ).json()
        assert summary["approved"] == 2
        assert summary["rejected"] == 1
        assert summary["pending"] == 0
        assert summary["completion_pct"] == pytest.approx(66.7)

    def test_bulk_approve_all_rejects_explicit_ids(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        r = client.post(
            f"/api/projects/{project}/test-sets/{ts_id}/questions/bulk",
            json={"action": "approve_all", "question_ids": [1]},
        )
        assert r.status_code == 422


class TestDeleteTestSet:
    def test_delete_test_set(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        r = client.delete(f"/api/projects/{project}/test-sets/{ts_id}")
        assert r.status_code == 204
        # Gone afterwards
        r2 = client.delete(f"/api/projects/{project}/test-sets/{ts_id}")
        assert r2.status_code == 404

    def test_delete_referenced_by_experiment_409(self, client, project):
        ts_id = _upload(client, project).json()["id"]
        _seed_experiment_for(project, ts_id)
        r = client.delete(f"/api/projects/{project}/test-sets/{ts_id}")
        assert r.status_code == 409
        assert "experiments" in r.json()["detail"]
