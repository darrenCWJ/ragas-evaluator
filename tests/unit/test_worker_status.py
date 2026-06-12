"""Worker service: status reporting and experiment/testgen endpoint contracts."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import worker.routes as worker_routes


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(worker_routes.router)
    return TestClient(app)


class TestWorkerStatus:
    def test_status_reports_all_task_type_counters(self):
        resp = _client().get("/status")
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "active_kg_builds",
            "active_persona_builds",
            "active_experiments",
            "active_testgens",
            "max_concurrent_kg",
            "max_concurrent_personas",
            "max_concurrent_experiments",
            "max_concurrent_testgens",
        ):
            assert field in data, f"missing {field}"
        assert data["tasks"] == []

    def test_status_reports_current_and_peak_memory(self):
        data = _client().get("/status").json()
        assert "rss_mb" in data
        assert "peak_rss_mb" in data
        # psutil is installed, so current RSS must be a real number
        assert isinstance(data["rss_mb"], (int, float))

    def test_health_reports_memory(self):
        data = _client().get("/health").json()
        assert data["status"] == "ok"
        assert "rss_mb" in data

    def test_status_includes_active_experiment_task(self):
        worker_routes._active_experiments[12345] = {"project_id": 7, "started_at": 1000.0}
        try:
            data = _client().get("/status").json()
            assert data["active_experiments"] == 1
            task = next(t for t in data["tasks"] if t["type"] == "experiment")
            assert task["experiment_id"] == 12345
            assert task["project_id"] == 7
        finally:
            worker_routes._active_experiments.pop(12345, None)

    def test_status_includes_active_testgen_task(self):
        worker_routes._active_testgens[321] = {"test_set_id": 9, "started_at": 1000.0}
        try:
            data = _client().get("/status").json()
            assert data["active_testgens"] == 1
            task = next(t for t in data["tasks"] if t["type"] == "testgen")
            assert task["project_id"] == 321
            assert task["test_set_id"] == 9
        finally:
            worker_routes._active_testgens.pop(321, None)


class TestExperimentEndpoints:
    def test_experiment_progress_unknown_returns_404(self):
        resp = _client().get("/experiment-progress/999999")
        assert resp.status_code == 404

    def test_cancel_experiment_unknown_returns_404(self):
        resp = _client().post("/cancel-experiment/999999")
        assert resp.status_code == 404

    def test_run_experiment_rejects_duplicate(self):
        worker_routes._active_experiments[777] = {"project_id": 1, "started_at": 0.0}
        try:
            resp = _client().post(
                "/run-experiment",
                json={"experiment_id": 777, "project_id": 1, "metrics": ["exact_match"]},
            )
            assert resp.status_code == 409
        finally:
            worker_routes._active_experiments.pop(777, None)


class TestTestgenEndpoints:
    def test_testgen_progress_inactive_returns_active_false(self):
        resp = _client().get("/testgen-progress/999999")
        assert resp.status_code == 200
        assert resp.json() == {"active": False}

    def test_cancel_testgen_unknown_returns_404(self):
        resp = _client().post("/cancel-testgen/999999")
        assert resp.status_code == 404

    def test_run_testgen_rejects_duplicate(self):
        worker_routes._active_testgens[555] = {"test_set_id": 1, "started_at": 0.0}
        try:
            resp = _client().post(
                "/run-testgen",
                json={"project_id": 555, "test_set_id": 1, "testset_size": 5},
            )
            assert resp.status_code == 409
        finally:
            worker_routes._active_testgens.pop(555, None)
