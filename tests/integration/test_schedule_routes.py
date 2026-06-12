"""Integration tests for schedule routes (regression runner patched out)."""

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
    name = f"sched-it-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


@pytest.fixture
def seeded(project):
    conn = db.init.get_db()
    try:
        bc = conn.execute(
            "INSERT INTO bot_configs (project_id, name, connector_type, config_json) VALUES (?, 'bot', 'custom', '{}')",
            (project,),
        ).lastrowid
        ts = conn.execute(
            "INSERT INTO test_sets (project_id, name) VALUES (?, 'sched-set')", (project,)
        ).lastrowid
        conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, status) VALUES (?, 'q?', 'a', 'approved')",
            (ts,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"pid": project, "bc": bc, "ts": ts}


def _payload(seeded, **overrides):
    return {
        "name": "nightly regression",
        "bot_config_id": seeded["bc"],
        "test_set_id": seeded["ts"],
        "interval_minutes": 60,
        **overrides,
    }


class TestScheduleCRUD:
    def test_create_and_list(self, client, seeded):
        resp = client.post(f"/api/projects/{seeded['pid']}/schedules", json=_payload(seeded))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["enabled"] is True
        assert body["metrics"]  # judge-free defaults
        assert body["last_run_at"] is None

        listed = client.get(f"/api/projects/{seeded['pid']}/schedules").json()
        assert len(listed) == 1
        assert listed[0]["open_alerts"] == 0

    def test_rejects_short_interval(self, client, seeded):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/schedules",
            json=_payload(seeded, interval_minutes=5),
        )
        assert resp.status_code == 422

    def test_rejects_unknown_metric(self, client, seeded):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/schedules",
            json=_payload(seeded, metrics=["nope"]),
        )
        assert resp.status_code == 400

    def test_rejects_private_webhook(self, client, seeded):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/schedules",
            json=_payload(seeded, webhook_url="http://localhost/hook"),
        )
        assert resp.status_code == 400
        assert "webhook_url" in resp.text

    def test_rejects_missing_bot_config(self, client, seeded):
        resp = client.post(
            f"/api/projects/{seeded['pid']}/schedules",
            json=_payload(seeded, bot_config_id=999999),
        )
        assert resp.status_code == 422

    def test_update_disable(self, client, seeded):
        sid = client.post(
            f"/api/projects/{seeded['pid']}/schedules", json=_payload(seeded)
        ).json()["id"]
        resp = client.put(
            f"/api/projects/{seeded['pid']}/schedules/{sid}",
            json={"enabled": False, "interval_minutes": 120},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        assert resp.json()["interval_minutes"] == 120

    def test_delete(self, client, seeded):
        sid = client.post(
            f"/api/projects/{seeded['pid']}/schedules", json=_payload(seeded)
        ).json()["id"]
        assert client.delete(f"/api/projects/{seeded['pid']}/schedules/{sid}").status_code == 204
        assert client.get(f"/api/projects/{seeded['pid']}/schedules/{sid}").status_code == 404


class TestRunNowAndAlerts:
    def test_run_now_dispatches_check(self, client, seeded):
        sid = client.post(
            f"/api/projects/{seeded['pid']}/schedules", json=_payload(seeded)
        ).json()["id"]
        with patch("app.routes.schedules.run_scheduled_check", AsyncMock()) as mock:
            resp = client.post(f"/api/projects/{seeded['pid']}/schedules/{sid}/run-now")
        assert resp.status_code == 202
        mock.assert_called_once_with(sid)

    def test_alert_listing_and_ack(self, client, seeded):
        sid = client.post(
            f"/api/projects/{seeded['pid']}/schedules", json=_payload(seeded)
        ).json()["id"]
        conn = db.init.get_db()
        alert_id = conn.execute(
            "INSERT INTO schedule_alerts (schedule_id, drops_json) VALUES (?, ?)",
            (sid, json.dumps([{"metric": "bleu_score", "baseline": 0.8, "current": 0.5, "drop": 0.3}])),
        ).lastrowid
        conn.commit()

        detail = client.get(f"/api/projects/{seeded['pid']}/schedules/{sid}").json()
        assert len(detail["alerts"]) == 1
        assert detail["alerts"][0]["acknowledged"] is False
        assert detail["alerts"][0]["drops"][0]["metric"] == "bleu_score"

        listed = client.get(f"/api/projects/{seeded['pid']}/schedules").json()
        assert listed[0]["open_alerts"] == 1

        resp = client.post(
            f"/api/projects/{seeded['pid']}/schedules/{sid}/alerts/{alert_id}/ack"
        )
        assert resp.status_code == 200
        listed = client.get(f"/api/projects/{seeded['pid']}/schedules").json()
        assert listed[0]["open_alerts"] == 0

    def test_ack_unknown_alert_404(self, client, seeded):
        sid = client.post(
            f"/api/projects/{seeded['pid']}/schedules", json=_payload(seeded)
        ).json()["id"]
        resp = client.post(f"/api/projects/{seeded['pid']}/schedules/{sid}/alerts/999/ack")
        assert resp.status_code == 404
