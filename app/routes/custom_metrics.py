"""CRUD routes for user-defined custom evaluation metrics."""

import json
import logging

from fastapi import APIRouter, HTTPException

from app.models import CustomMetricCreate
from evaluation.scoring import ALL_METRICS
import db.init

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["custom_metrics"])


def _parse_custom_metric_row(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "metric_type": row["metric_type"],
        "prompt": row["prompt"],
        "rubrics": json.loads(row["rubrics_json"]) if row["rubrics_json"] else None,
        "min_score": row["min_score"],
        "max_score": row["max_score"],
        "created_at": row["created_at"],
    }


@router.get("/projects/{project_id}/custom-metrics")
async def list_custom_metrics(project_id: int):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM custom_metrics WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [_parse_custom_metric_row(r) for r in rows]


@router.post("/projects/{project_id}/custom-metrics", status_code=201)
async def create_custom_metric(project_id: int, req: CustomMetricCreate):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Prevent name collision with built-in metrics
    if req.name in ALL_METRICS:
        raise HTTPException(
            status_code=409,
            detail=f"'{req.name}' conflicts with a built-in metric name",
        )

    # Prevent duplicate custom metric names within project
    existing = conn.execute(
        "SELECT id FROM custom_metrics WHERE project_id = ? AND name = ?",
        (project_id, req.name),
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Custom metric '{req.name}' already exists in this project",
        )

    cursor = conn.execute(
        """INSERT INTO custom_metrics
           (project_id, name, metric_type, prompt, rubrics_json, min_score, max_score)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            req.name,
            req.metric_type,
            req.prompt,
            json.dumps(req.rubrics) if req.rubrics else None,
            req.min_score,
            req.max_score,
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM custom_metrics WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _parse_custom_metric_row(row)


@router.delete("/projects/{project_id}/custom-metrics/{metric_id}")
async def delete_custom_metric(project_id: int, metric_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id FROM custom_metrics WHERE id = ? AND project_id = ?",
        (metric_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Custom metric not found")

    conn.execute("DELETE FROM custom_metrics WHERE id = ?", (metric_id,))
    conn.commit()
    return {"deleted": True}
