"""Integration tests for Skill Arena routes — full trial with mocked LLM layer.

No real API keys needed: parse_skill and the cell-level model/judge calls are
patched, so these tests exercise routing, persistence, the trial runner's
matrix execution, tracing, and aggregation end-to-end.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import main

pytestmark = pytest.mark.integration

PARSED = {
    "name": "test-skill",
    "summary": "A test skill",
    "directives": [
        {"id": "d1", "text": "Answer politely", "kind": "behavior", "machine_checkable": False},
        {"id": "d2", "text": "Respond in valid JSON", "kind": "format", "machine_checkable": True},
    ],
}


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def project(client):
    resp = client.post("/api/projects", json={"name": "skill-arena-it", "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _make_test_set(pid: int) -> int:
    """Seed a test set with two approved questions directly in the DB."""
    import db.init

    conn = db.init.get_db()
    cur = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, ?)",
        (pid, "skill-it-set"),
    )
    test_set_id = cur.lastrowid
    for q, a in [
        ("What is the refund policy?", "30 days."),
        ("How do I reset my password?", "Settings page."),
    ]:
        conn.execute(
            """INSERT INTO test_questions
               (test_set_id, question, reference_answer, reference_contexts, question_type, persona, status)
               VALUES (?, ?, ?, '[]', 'uploaded', '', 'approved')""",
            (test_set_id, q, a),
        )
    conn.commit()
    return test_set_id


class TestSkillCrud:
    def test_upload_parse_version_and_delete(self, client, project):
        with patch("app.routes.skills.parse_skill", new=AsyncMock(return_value=PARSED)):
            r1 = client.post(
                f"/api/projects/{project}/skills",
                json={"content": "# My skill\n\n- Answer politely\n- Respond in JSON"},
            )
            assert r1.status_code == 201, r1.text
            skill = r1.json()
            assert skill["name"] == "test-skill"
            assert skill["version"] == 1
            assert skill["directive_count"] == 2

            # Same name → version bumps
            r2 = client.post(
                f"/api/projects/{project}/skills",
                json={"content": "# My skill v2 content", "name": "test-skill"},
            )
            assert r2.json()["version"] == 2

        listing = client.get(f"/api/projects/{project}/skills").json()
        assert len(listing) == 2

        rd = client.delete(f"/api/projects/{project}/skills/{skill['id']}")
        assert rd.status_code == 200

    def test_unparseable_skill_rejected(self, client, project):
        with patch(
            "app.routes.skills.parse_skill",
            new=AsyncMock(side_effect=ValueError("No testable directives")),
        ):
            r = client.post(
                f"/api/projects/{project}/skills",
                json={"content": "just some text with no rules in it at all"},
            )
        assert r.status_code == 422
        assert "directives" in r.json()["detail"]

    def test_trial_requires_existing_skill(self, client, project):
        r = client.post(
            f"/api/projects/{project}/skill-trials",
            json={
                "name": "t", "skill_id": 99999, "test_set_id": 1,
                "models": [{"kind": "llm", "model": "gpt-4o-mini"}],
            },
        )
        assert r.status_code == 404

    def test_model_spec_validation(self, client, project):
        r = client.post(
            f"/api/projects/{project}/skill-trials",
            json={
                "name": "t", "skill_id": 1, "test_set_id": 1,
                "models": [{"kind": "nonsense"}],
            },
        )
        assert r.status_code == 422


class TestTrialEndToEnd:
    def test_full_trial_matrix(self, client, project):
        test_set_id = _make_test_set(project)

        with patch("app.routes.skills.parse_skill", new=AsyncMock(return_value=PARSED)):
            skill_id = client.post(
                f"/api/projects/{project}/skills",
                json={"content": "# Skill\n\n- Answer politely\n- Respond in JSON"},
            ).json()["id"]

        fake_reply = {"answer": '{"reply": "ok"}', "tokens_in": 11, "tokens_out": 7}
        fake_verdicts = {
            "score": 1.0,
            "results": [
                {"id": "d1", "verdict": "pass", "reasoning": "ok", "deterministic": False},
                {"id": "d2", "verdict": "pass", "reasoning": "ok", "deterministic": True},
            ],
            "judge_usage": {},
        }
        with (
            patch("app.services.skill_trials._query_model", new=AsyncMock(return_value=fake_reply)),
            patch("app.services.skill_trials.judge_adherence", new=AsyncMock(return_value=fake_verdicts)),
        ):
            start = client.post(
                f"/api/projects/{project}/skill-trials",
                json={
                    "name": "matrix run",
                    "skill_id": skill_id,
                    "test_set_id": test_set_id,
                    "models": [
                        {"kind": "llm", "model": "gpt-4o-mini"},
                        {"kind": "llm", "model": "claude-haiku-4-5"},
                    ],
                    "include_baseline": True,
                },
            )
            assert start.status_code == 201, start.text
            trial_id = start.json()["trial_id"]
            # 2 questions × 2 models × 2 variants
            assert start.json()["total_cells"] == 8

            # TestClient drives the event loop between requests; poll until done
            for _ in range(200):
                prog = client.get(
                    f"/api/projects/{project}/skill-trials/{trial_id}/progress"
                ).json()
                if prog.get("phase") in ("completed", "error", "failed"):
                    break
            assert prog.get("phase") == "completed", prog

        detail = client.get(f"/api/projects/{project}/skill-trials/{trial_id}").json()
        assert detail["status"] == "completed"
        matrix = detail["matrix"]
        assert len(matrix["cells"]) == 4  # 2 models × 2 variants
        for cell in matrix["cells"]:
            assert cell["adherence"] == 1.0
            assert cell["count"] == 2
        assert matrix["lift"] == {"gpt-4o-mini": 0.0, "claude-haiku-4-5": 0.0}

        results = client.get(
            f"/api/projects/{project}/skill-trials/{trial_id}/results",
            params={"model": "gpt-4o-mini", "variant": "skill"},
        ).json()
        assert len(results) == 2
        first = results[0]
        assert first["scores"]["skill_adherence"] == 1.0
        assert [s["name"] for s in first["trace"]] == ["prepare", "query", "judge"]
        assert first["tokens_in"] == 11

    def test_apply_model(self, client, project):
        r = client.post(
            f"/api/projects/{project}/apply-model", json={"model": "claude-haiku-4-5"}
        )
        assert r.status_code == 200
        proj = client.get(f"/api/projects/{project}").json()
        assert proj["preferred_model"] == "claude-haiku-4-5"
