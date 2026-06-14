"""Persisted retry queue for worker-dispatched jobs.

Previously, a KG build hitting "all workers busy" returned 503 and the user
had to retry by hand. Now the request is parked in the ``pending_jobs`` table
and a background loop re-offers it to the workers until one accepts. The
queue survives main-app restarts (rows are persisted; the loop re-reads them
on startup).

Currently used for KG builds — experiments and testgen already fall back to
local execution, so they never need to queue.
"""

from __future__ import annotations

import asyncio
import json
import logging

import db.init

logger = logging.getLogger(__name__)

DISPATCH_INTERVAL_SECONDS = 20
MAX_ATTEMPTS = 90  # ~30 minutes of retries before giving up

KIND_KG_BUILD = "kg_build"


def enqueue_kg_build(conn, project_id: int, kg_source: str, payload: dict) -> bool:
    """Queue a KG build for retry dispatch. False when already queued."""
    dedupe_key = f"{KIND_KG_BUILD}:{project_id}:{kg_source}"
    try:
        conn.execute(
            "INSERT INTO pending_jobs (kind, project_id, dedupe_key, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (KIND_KG_BUILD, project_id, dedupe_key, json.dumps(payload)),
        )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        if db.init.is_integrity_error(exc):
            return False
        raise


def list_queued(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, kind, project_id, dedupe_key, payload_json, attempts, created_at "
        "FROM pending_jobs ORDER BY id"
    ).fetchall()
    out = []
    for row in rows:
        entry = dict(row)
        try:
            entry["payload"] = json.loads(entry.pop("payload_json"))
        except (TypeError, ValueError):
            entry["payload"] = {}
        out.append(entry)
    return out


def is_queued(conn, project_id: int, kg_source: str) -> bool:
    return (
        conn.execute(
            "SELECT id FROM pending_jobs WHERE dedupe_key = ?",
            (f"{KIND_KG_BUILD}:{project_id}:{kg_source}",),
        ).fetchone()
        is not None
    )


def remove_job(conn, job_id: int) -> None:
    conn.execute("DELETE FROM pending_jobs WHERE id = ?", (job_id,))
    conn.commit()


async def _try_dispatch_kg(payload: dict) -> str | None:
    """Offer a queued KG build to each worker; the accepting worker's URL or None."""
    import httpx

    from config import KG_WORKER_URLS

    async with httpx.AsyncClient(timeout=10) as client:
        for worker_url in KG_WORKER_URLS:
            try:
                resp = await client.post(f"{worker_url}/build-kg", json=payload)
                if resp.status_code == 202:
                    return worker_url
                if resp.status_code == 409:
                    # Already building somewhere — treat as dispatched
                    return worker_url
            except Exception as exc:
                logger.debug("Queue dispatch: worker %s unreachable: %s", worker_url, exc)
    return None


async def dispatch_pending_jobs_once() -> int:
    """One queue pass; returns how many jobs were dispatched (or dropped)."""
    conn = db.init.get_db()
    jobs = list_queued(conn)
    if not jobs:
        return 0

    handled = 0
    for job in jobs:
        if job["kind"] != KIND_KG_BUILD:
            continue
        worker_url = await _try_dispatch_kg(job["payload"])
        if worker_url is not None:
            from app.routes.testsets import _project_worker

            kg_source = job["payload"].get("kg_source", "chunks")
            _project_worker[(job["project_id"], kg_source)] = worker_url
            remove_job(conn, job["id"])
            handled += 1
            logger.info(
                "Queued KG build dispatched: project=%d source=%s worker=%s (attempt %d)",
                job["project_id"], kg_source, worker_url, job["attempts"] + 1,
            )
            continue

        attempts = job["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            remove_job(conn, job["id"])
            handled += 1
            logger.warning(
                "Queued KG build dropped after %d attempts: project=%d",
                attempts, job["project_id"],
            )
        else:
            conn.execute(
                "UPDATE pending_jobs SET attempts = ? WHERE id = ?", (attempts, job["id"])
            )
            conn.commit()
    return handled


async def dispatch_loop() -> None:
    """Background retry loop — started from the app lifespan."""
    logger.info("Job-queue dispatch loop started (interval %ds)", DISPATCH_INTERVAL_SECONDS)
    while True:
        try:
            await dispatch_pending_jobs_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Job-queue dispatch pass failed", exc_info=True)
        await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)
