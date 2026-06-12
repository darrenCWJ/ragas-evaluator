"""Scheduled regression run routes: CRUD, run-now, and drop alerts."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException

import db.init
from app.models import ScheduleCreate, ScheduleUpdate
from app.services.schedule_service import DEFAULT_SCHEDULE_METRICS, run_scheduled_check
from evaluation.scoring import ALL_METRICS
from pipeline.bot_connectors.custom import _validate_endpoint_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["schedules"])


def _parse_schedule_row(row) -> dict:
    d = dict(row)
    d["metrics"] = json.loads(d.pop("metrics_json"))
    d["enabled"] = bool(d["enabled"])
    return d


def _get_schedule(conn, project_id: int, schedule_id: int):
    row = conn.execute(
        "SELECT * FROM schedules WHERE id = ? AND project_id = ?",
        (schedule_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return row


def _validate_webhook(url: str | None) -> None:
    if url is None:
        return
    try:
        # Same SSRF guard as custom bot endpoints (private-IP + scheme checks).
        _validate_endpoint_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"webhook_url: {exc}") from exc


def _validate_metrics(metrics: list[str] | None) -> list[str]:
    chosen = metrics or DEFAULT_SCHEDULE_METRICS
    invalid = [m for m in chosen if m not in ALL_METRICS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown metrics: {', '.join(invalid)}")
    return chosen


@router.post("/projects/{project_id}/schedules", status_code=201)
async def create_schedule(project_id: int, body: ScheduleCreate):
    conn = db.init.get_db()

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    bot_config = conn.execute(
        "SELECT id, connector_type FROM bot_configs WHERE id = ? AND project_id = ?",
        (body.bot_config_id, project_id),
    ).fetchone()
    if bot_config is None:
        raise HTTPException(status_code=422, detail="Bot config not found in this project")

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

    metrics = _validate_metrics(body.metrics)
    _validate_webhook(body.webhook_url)

    cursor = conn.execute(
        """INSERT INTO schedules
           (project_id, name, bot_config_id, test_set_id, metrics_json,
            interval_minutes, alert_drop_threshold, webhook_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            body.name,
            body.bot_config_id,
            body.test_set_id,
            json.dumps(metrics),
            body.interval_minutes,
            body.alert_drop_threshold,
            body.webhook_url,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM schedules WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _parse_schedule_row(row)


@router.get("/projects/{project_id}/schedules")
async def list_schedules(project_id: int):
    conn = db.init.get_db()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM schedules WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    schedules = []
    for row in rows:
        open_alerts = conn.execute(
            "SELECT COUNT(*) AS cnt FROM schedule_alerts WHERE schedule_id = ? AND acknowledged = 0",
            (row["id"],),
        ).fetchone()["cnt"]
        schedules.append({**_parse_schedule_row(row), "open_alerts": open_alerts})
    return schedules


@router.get("/projects/{project_id}/schedules/{schedule_id}")
async def get_schedule(project_id: int, schedule_id: int):
    conn = db.init.get_db()
    row = _get_schedule(conn, project_id, schedule_id)
    alerts = conn.execute(
        "SELECT * FROM schedule_alerts WHERE schedule_id = ? ORDER BY created_at DESC LIMIT 50",
        (schedule_id,),
    ).fetchall()
    return {
        **_parse_schedule_row(row),
        "alerts": [
            {
                "id": a["id"],
                "experiment_id": a["experiment_id"],
                "baseline_experiment_id": a["baseline_experiment_id"],
                "drops": json.loads(a["drops_json"]),
                "acknowledged": bool(a["acknowledged"]),
                "created_at": a["created_at"],
            }
            for a in alerts
        ],
    }


@router.put("/projects/{project_id}/schedules/{schedule_id}")
async def update_schedule(project_id: int, schedule_id: int, body: ScheduleUpdate):
    conn = db.init.get_db()
    _get_schedule(conn, project_id, schedule_id)

    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.interval_minutes is not None:
        updates["interval_minutes"] = body.interval_minutes
    if body.metrics is not None:
        updates["metrics_json"] = json.dumps(_validate_metrics(body.metrics))
    if body.alert_drop_threshold is not None:
        updates["alert_drop_threshold"] = body.alert_drop_threshold
    if body.webhook_url is not None:
        _validate_webhook(body.webhook_url)
        updates["webhook_url"] = body.webhook_url
    if body.enabled is not None:
        updates["enabled"] = int(body.enabled)

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE schedules SET {set_clause} WHERE id = ?",
            (*updates.values(), schedule_id),
        )
        conn.commit()

    row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    return _parse_schedule_row(row)


@router.delete("/projects/{project_id}/schedules/{schedule_id}", status_code=204)
async def delete_schedule(project_id: int, schedule_id: int):
    conn = db.init.get_db()
    _get_schedule(conn, project_id, schedule_id)
    conn.execute("DELETE FROM schedule_alerts WHERE schedule_id = ?", (schedule_id,))
    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    conn.commit()


@router.post("/projects/{project_id}/schedules/{schedule_id}/run-now", status_code=202)
async def run_schedule_now(project_id: int, schedule_id: int):
    conn = db.init.get_db()
    _get_schedule(conn, project_id, schedule_id)
    asyncio.create_task(run_scheduled_check(schedule_id))
    return {"detail": "Regression run started"}


@router.post("/projects/{project_id}/schedules/{schedule_id}/alerts/{alert_id}/ack")
async def acknowledge_alert(project_id: int, schedule_id: int, alert_id: int):
    conn = db.init.get_db()
    _get_schedule(conn, project_id, schedule_id)
    cursor = conn.execute(
        "UPDATE schedule_alerts SET acknowledged = 1 WHERE id = ? AND schedule_id = ?",
        (alert_id, schedule_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"detail": "Alert acknowledged"}
