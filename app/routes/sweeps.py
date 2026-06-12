"""Parameter sweep routes: create/run a retrieval-parameter grid, watch
progress, read the leaderboard, cancel, delete."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query

import db.init
from app.models import SweepCreate
from app.services.sweep_service import (
    DEFAULT_SWEEP_METRICS,
    expand_grid,
    run_sweep_background,
    sweep_leaderboard,
)
from evaluation.scoring import ALL_METRICS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sweeps"])


def _parse_sweep_row(row) -> dict:
    d = dict(row)
    d["grid"] = json.loads(d.pop("grid_json"))
    d["metrics"] = json.loads(d.pop("metrics_json"))
    return d


def _get_sweep(conn, project_id: int, sweep_id: int):
    row = conn.execute(
        "SELECT * FROM sweeps WHERE id = ? AND project_id = ?", (sweep_id, project_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sweep not found")
    return row


@router.post("/projects/{project_id}/sweeps", status_code=201)
async def create_sweep(project_id: int, body: SweepCreate):
    """Create a sweep and start running it in the background."""
    conn = db.init.get_db()

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    test_set = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (body.test_set_id, project_id),
    ).fetchone()
    if test_set is None:
        raise HTTPException(status_code=422, detail="Test set not found in this project")

    approved = conn.execute(
        "SELECT COUNT(*) AS cnt FROM test_questions WHERE test_set_id = ?"
        " AND status IN ('approved', 'edited')",
        (body.test_set_id,),
    ).fetchone()["cnt"]
    if approved == 0:
        raise HTTPException(status_code=422, detail="Test set has no approved questions")

    rag_config = conn.execute(
        "SELECT id FROM rag_configs WHERE id = ? AND project_id = ?",
        (body.rag_config_id, project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(status_code=422, detail="RAG config not found in this project")

    metrics = body.metrics or DEFAULT_SWEEP_METRICS
    invalid = [m for m in metrics if m not in ALL_METRICS]
    if invalid:
        raise HTTPException(
            status_code=400, detail=f"Unknown metrics: {', '.join(invalid)}"
        )

    combos = expand_grid(body.grid)

    cursor = conn.execute(
        """INSERT INTO sweeps
           (project_id, name, test_set_id, base_rag_config_id, grid_json, metrics_json, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (
            project_id,
            body.name,
            body.test_set_id,
            body.rag_config_id,
            json.dumps(body.grid),
            json.dumps(metrics),
        ),
    )
    sweep_id = cursor.lastrowid
    for params in combos:
        conn.execute(
            "INSERT INTO sweep_runs (sweep_id, params_json) VALUES (?, ?)",
            (sweep_id, json.dumps(params)),
        )
    conn.commit()

    asyncio.create_task(run_sweep_background(sweep_id))
    logger.info("Sweep %d created with %d combinations", sweep_id, len(combos))

    row = conn.execute("SELECT * FROM sweeps WHERE id = ?", (sweep_id,)).fetchone()
    return {**_parse_sweep_row(row), "num_runs": len(combos)}


@router.get("/projects/{project_id}/sweeps")
async def list_sweeps(
    project_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    conn = db.init.get_db()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM sweeps WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (project_id, limit, offset),
    ).fetchall()
    sweeps = []
    for row in rows:
        counts = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM sweep_runs WHERE sweep_id = ? GROUP BY status",
            (row["id"],),
        ).fetchall()
        sweeps.append(
            {**_parse_sweep_row(row), "run_counts": {c["status"]: c["cnt"] for c in counts}}
        )
    return sweeps


@router.get("/projects/{project_id}/sweeps/{sweep_id}")
async def get_sweep(project_id: int, sweep_id: int):
    conn = db.init.get_db()
    row = _get_sweep(conn, project_id, sweep_id)
    runs = conn.execute(
        "SELECT * FROM sweep_runs WHERE sweep_id = ? ORDER BY id", (sweep_id,)
    ).fetchall()
    return {
        **_parse_sweep_row(row),
        "runs": [
            {
                "id": r["id"],
                "experiment_id": r["experiment_id"],
                "params": json.loads(r["params_json"]),
                "status": r["status"],
            }
            for r in runs
        ],
    }


@router.get("/projects/{project_id}/sweeps/{sweep_id}/leaderboard")
async def get_sweep_leaderboard(project_id: int, sweep_id: int):
    conn = db.init.get_db()
    row = _get_sweep(conn, project_id, sweep_id)
    return {
        "sweep_id": sweep_id,
        "status": row["status"],
        "leaderboard": sweep_leaderboard(conn, sweep_id),
    }


@router.post("/projects/{project_id}/sweeps/{sweep_id}/cancel")
async def cancel_sweep(project_id: int, sweep_id: int):
    conn = db.init.get_db()
    row = _get_sweep(conn, project_id, sweep_id)
    if row["status"] in ("completed", "completed_with_failures", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Sweep already {row['status']}")
    conn.execute("UPDATE sweeps SET status = 'cancelled' WHERE id = ?", (sweep_id,))
    conn.execute(
        "UPDATE sweep_runs SET status = 'cancelled' WHERE sweep_id = ? AND status = 'pending'",
        (sweep_id,),
    )
    conn.commit()
    return {"detail": "Sweep cancelled — the in-flight experiment finishes, queued runs stop"}


@router.delete("/projects/{project_id}/sweeps/{sweep_id}", status_code=204)
async def delete_sweep(project_id: int, sweep_id: int):
    conn = db.init.get_db()
    row = _get_sweep(conn, project_id, sweep_id)
    if row["status"] == "running":
        raise HTTPException(status_code=409, detail="Cancel the sweep before deleting it")
    conn.execute("DELETE FROM sweep_runs WHERE sweep_id = ?", (sweep_id,))
    conn.execute("DELETE FROM sweeps WHERE id = ?", (sweep_id,))
    conn.commit()
