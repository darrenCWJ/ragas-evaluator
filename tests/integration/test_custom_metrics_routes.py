"""Integration tests for custom metric routes — CRUD, type validation, refine-description.

The refine-description endpoint's LLM call is mocked at the route module
(custom_metrics imports chat_completion at module level), so no API calls.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import main

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def project(client):
    name = f"metrics-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _create(client, pid: int, **overrides):
    payload = {
        "name": "politeness",
        "metric_type": "integer_range",
        "prompt": "Score how polite the response is.",
        "min_score": 1,
        "max_score": 5,
    }
    payload.update(overrides)
    return client.post(f"/api/projects/{pid}/custom-metrics", json=payload)


class TestCreateAndList:
    def test_create_integer_range_and_list(self, client, project):
        r = _create(client, project)
        assert r.status_code == 201, r.text
        metric = r.json()
        assert metric["name"] == "politeness"
        assert metric["metric_type"] == "integer_range"
        assert metric["min_score"] == 1
        assert metric["max_score"] == 5
        assert metric["rubrics"] is None

        listed = client.get(f"/api/projects/{project}/custom-metrics")
        assert listed.status_code == 200
        assert [m["id"] for m in listed.json()] == [metric["id"]]

    def test_create_similarity_type(self, client, project):
        r = _create(
            client, project,
            name="tone_match",
            metric_type="similarity",
            prompt="Compare tone with the reference.",
        )
        assert r.status_code == 201, r.text
        assert r.json()["metric_type"] == "similarity"

    def test_create_rubrics_type_round_trips_rubrics(self, client, project):
        rubrics = {
            "score1_description": "Completely off-brand.",
            "score5_description": "Perfectly on-brand.",
        }
        r = _create(
            client, project,
            name="brand_voice",
            metric_type="rubrics",
            prompt=None,
            rubrics=rubrics,
        )
        assert r.status_code == 201, r.text
        assert r.json()["rubrics"] == rubrics

    def test_create_instance_rubrics_type(self, client, project):
        r = _create(
            client, project,
            name="per_question_quality",
            metric_type="instance_rubrics",
            prompt=None,
        )
        assert r.status_code == 201, r.text
        assert r.json()["metric_type"] == "instance_rubrics"


class TestTypeValidation:
    def test_integer_range_requires_prompt(self, client, project):
        r = _create(client, project, prompt=None)
        assert r.status_code == 422

    def test_rubrics_type_requires_rubrics(self, client, project):
        r = _create(client, project, name="needs_rubrics", metric_type="rubrics", rubrics=None)
        assert r.status_code == 422

    def test_unknown_metric_type_rejected(self, client, project):
        r = _create(client, project, metric_type="vibes")
        assert r.status_code == 422

    def test_invalid_name_rejected(self, client, project):
        r = _create(client, project, name="Not A Valid Name")
        assert r.status_code == 422

    def test_invalid_score_range_rejected(self, client, project):
        assert _create(client, project, min_score=5, max_score=5).status_code == 422
        assert _create(client, project, min_score=1, max_score=11).status_code == 422

    def test_builtin_name_collision_409(self, client, project):
        r = _create(client, project, name="faithfulness")
        assert r.status_code == 409
        assert "built-in" in r.json()["detail"]

    def test_duplicate_name_in_project_409(self, client, project):
        assert _create(client, project).status_code == 201
        r = _create(client, project)
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]


class TestUpdateAndDelete:
    def test_update_metric(self, client, project):
        metric_id = _create(client, project).json()["id"]
        r = client.put(
            f"/api/projects/{project}/custom-metrics/{metric_id}",
            json={
                "name": "politeness",
                "metric_type": "integer_range",
                "prompt": "Updated scoring prompt.",
                "min_score": 0,
                "max_score": 10,
            },
        )
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["prompt"] == "Updated scoring prompt."
        assert updated["min_score"] == 0
        assert updated["max_score"] == 10

    def test_update_unknown_metric_404(self, client, project):
        r = client.put(
            f"/api/projects/{project}/custom-metrics/99999999",
            json={
                "name": "ghost",
                "metric_type": "integer_range",
                "prompt": "x",
            },
        )
        assert r.status_code == 404

    def test_delete_metric(self, client, project):
        metric_id = _create(client, project).json()["id"]
        r = client.delete(f"/api/projects/{project}/custom-metrics/{metric_id}")
        assert r.status_code == 200
        assert r.json() == {"deleted": True}
        assert client.get(f"/api/projects/{project}/custom-metrics").json() == []
        # Second delete -> 404
        assert (
            client.delete(f"/api/projects/{project}/custom-metrics/{metric_id}").status_code
            == 404
        )

    def test_unknown_project_404(self, client):
        assert client.get("/api/projects/99999999/custom-metrics").status_code == 404
        assert _create(client, 99999999).status_code == 404


class TestRefineDescription:
    def test_refine_description_with_mocked_llm(self, client, project):
        fake = AsyncMock(return_value={"content": "  Evaluate politeness precisely.  "})
        with patch("app.routes.custom_metrics.chat_completion", new=fake):
            r = client.post(
                f"/api/projects/{project}/custom-metrics/refine-description",
                json={"description": "I want to measure how polite the bot is."},
            )
        assert r.status_code == 200, r.text
        assert r.json() == {"refined_prompt": "Evaluate politeness precisely."}
        assert fake.await_count == 1
        # The user's description is forwarded to the LLM
        messages = fake.await_args.args[1]
        assert "how polite the bot is" in messages[1]["content"]

    def test_refine_llm_failure_502(self, client, project):
        fake = AsyncMock(side_effect=RuntimeError("provider down"))
        with patch("app.routes.custom_metrics.chat_completion", new=fake):
            r = client.post(
                f"/api/projects/{project}/custom-metrics/refine-description",
                json={"description": "measure politeness"},
            )
        assert r.status_code == 502

    def test_refine_empty_description_422(self, client, project):
        r = client.post(
            f"/api/projects/{project}/custom-metrics/refine-description",
            json={"description": "   "},
        )
        assert r.status_code == 422
