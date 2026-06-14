"""Persisted KG-build retry queue."""

from unittest.mock import AsyncMock, patch

from app.services import job_queue

PAYLOAD = {"project_id": 1, "chunk_config_id": None, "kg_source": "chunks",
           "overlap_max_nodes": 500, "fast_mode": False}


class TestEnqueue:
    def test_enqueue_and_list(self, sample_project):
        conn, pid = sample_project
        assert job_queue.enqueue_kg_build(conn, pid, "chunks", {**PAYLOAD, "project_id": pid})
        jobs = job_queue.list_queued(conn)
        assert len(jobs) == 1
        assert jobs[0]["kind"] == "kg_build"
        assert jobs[0]["payload"]["kg_source"] == "chunks"
        assert job_queue.is_queued(conn, pid, "chunks") is True

    def test_duplicate_enqueue_rejected(self, sample_project):
        conn, pid = sample_project
        assert job_queue.enqueue_kg_build(conn, pid, "chunks", PAYLOAD) is True
        assert job_queue.enqueue_kg_build(conn, pid, "chunks", PAYLOAD) is False
        assert len(job_queue.list_queued(conn)) == 1

    def test_different_sources_queue_separately(self, sample_project):
        conn, pid = sample_project
        assert job_queue.enqueue_kg_build(conn, pid, "chunks", PAYLOAD)
        assert job_queue.enqueue_kg_build(conn, pid, "documents", PAYLOAD)
        assert len(job_queue.list_queued(conn)) == 2


class TestDispatch:
    async def test_dispatch_removes_job_on_acceptance(self, sample_project):
        conn, pid = sample_project
        job_queue.enqueue_kg_build(conn, pid, "chunks", {**PAYLOAD, "project_id": pid})

        with patch.object(
            job_queue, "_try_dispatch_kg", new=AsyncMock(return_value="http://worker:9000")
        ):
            handled = await job_queue.dispatch_pending_jobs_once()
        assert handled == 1
        assert job_queue.list_queued(conn) == []

    async def test_dispatch_increments_attempts_when_all_busy(self, sample_project):
        conn, pid = sample_project
        job_queue.enqueue_kg_build(conn, pid, "chunks", PAYLOAD)

        with patch.object(job_queue, "_try_dispatch_kg", new=AsyncMock(return_value=None)):
            await job_queue.dispatch_pending_jobs_once()
        jobs = job_queue.list_queued(conn)
        assert jobs[0]["attempts"] == 1

    async def test_job_dropped_after_max_attempts(self, sample_project):
        conn, pid = sample_project
        job_queue.enqueue_kg_build(conn, pid, "chunks", PAYLOAD)
        conn.execute(
            "UPDATE pending_jobs SET attempts = ?", (job_queue.MAX_ATTEMPTS - 1,)
        )
        conn.commit()

        with patch.object(job_queue, "_try_dispatch_kg", new=AsyncMock(return_value=None)):
            handled = await job_queue.dispatch_pending_jobs_once()
        assert handled == 1
        assert job_queue.list_queued(conn) == []
