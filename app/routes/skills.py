"""Skill Arena routes — skill file CRUD, cross-model trials, and model apply.

A *skill* is a SKILL.md-style instruction document. A *trial* runs a matrix of
(skill | baseline) × selected AI models × an approved test set, judging every
response against the skill's directive checklist. The winning model can be
applied as the project's preferred model.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query

import db.init
from app.models import ApplyModelRequest, SkillCreate, SkillTrialCreate
from app.services.skill_trials import (
    aggregate_trial_matrix,
    run_skill_trial,
    skill_trial_runs,
)
from db.init import NOW_SQL
from evaluation.skills.parser import parse_skill

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["skills"])


def _require_project(conn, project_id: int) -> None:
    if conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _format_skill(row, include_content: bool = False) -> dict:
    parsed = json.loads(row["parsed_directives_json"]) if row["parsed_directives_json"] else None
    out = {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "version": row["version"],
        "summary": (parsed or {}).get("summary", ""),
        "directive_count": len((parsed or {}).get("directives", [])),
        "directives": (parsed or {}).get("directives", []),
        "created_at": row["created_at"],
    }
    if include_content:
        out["content"] = row["content"]
    return out


# --- Skill CRUD -------------------------------------------------------------


@router.post("/projects/{project_id}/skills", status_code=201)
async def upload_skill(project_id: int, req: SkillCreate):
    """Upload/paste a skill file. Parses directives immediately — a skill that
    yields no testable directives is rejected rather than stored unusable."""
    conn = db.init.get_db()
    _require_project(conn, project_id)

    try:
        parsed = await parse_skill(req.content)
    except Exception as exc:
        logger.warning("Skill parse failed for project %d: %s", project_id, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract testable directives from the skill file: {exc}",
        ) from exc

    name = (req.name or parsed["name"]).strip()
    prev = conn.execute(
        "SELECT MAX(version) AS v FROM skills WHERE project_id = ? AND name = ?",
        (project_id, name),
    ).fetchone()
    version = (prev["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO skills (project_id, name, version, content, parsed_directives_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, name, version, req.content, json.dumps(parsed)),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM skills WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _format_skill(row, include_content=True)


@router.get("/projects/{project_id}/skills")
async def list_skills(project_id: int, limit: int = Query(default=200, ge=1, le=1000)):
    conn = db.init.get_db()
    _require_project(conn, project_id)
    rows = conn.execute(
        "SELECT * FROM skills WHERE project_id = ? ORDER BY name, version DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [_format_skill(r) for r in rows]


@router.get("/projects/{project_id}/skills/{skill_id}")
async def get_skill(project_id: int, skill_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT * FROM skills WHERE id = ? AND project_id = ?", (skill_id, project_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _format_skill(row, include_content=True)


@router.delete("/projects/{project_id}/skills/{skill_id}")
async def delete_skill(project_id: int, skill_id: int):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM skills WHERE id = ? AND project_id = ?", (skill_id, project_id)
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    conn.commit()
    return {"detail": "Skill deleted"}


# --- Trial lifecycle ----------------------------------------------------------


def _format_trial(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "skill_id": row["skill_id"],
        "name": row["name"],
        "test_set_id": row["test_set_id"],
        "models": json.loads(row["models_json"]),
        "include_baseline": bool(row["include_baseline"]),
        "status": row["status"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


@router.post("/projects/{project_id}/skill-trials", status_code=201)
async def create_skill_trial(project_id: int, req: SkillTrialCreate):
    conn = db.init.get_db()
    _require_project(conn, project_id)

    skill = conn.execute(
        "SELECT id, parsed_directives_json FROM skills WHERE id = ? AND project_id = ?",
        (req.skill_id, project_id),
    ).fetchone()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    ts = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (req.test_set_id, project_id),
    ).fetchone()
    if ts is None:
        raise HTTPException(status_code=404, detail="Test set not found")
    q_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
        (req.test_set_id,),
    ).fetchone()["cnt"]
    if q_count == 0:
        raise HTTPException(status_code=409, detail="Test set has no approved questions")

    for spec in req.models:
        if spec.get("kind") == "bot":
            bot = conn.execute(
                "SELECT id FROM bot_configs WHERE id = ? AND project_id = ?",
                (spec.get("bot_config_id"), project_id),
            ).fetchone()
            if bot is None:
                raise HTTPException(
                    status_code=404, detail=f"Bot config {spec.get('bot_config_id')} not found"
                )

    cur = conn.execute(
        "INSERT INTO skill_trials (project_id, skill_id, name, test_set_id, models_json, include_baseline) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            project_id, req.skill_id, req.name, req.test_set_id,
            json.dumps(req.models), 1 if req.include_baseline else 0,
        ),
    )
    conn.commit()
    trial_id = cur.lastrowid

    task = asyncio.create_task(run_skill_trial(trial_id))
    skill_trial_runs.set_task(trial_id, task)

    variants = 2 if req.include_baseline else 1
    return {
        "trial_id": trial_id,
        "status": "started",
        "total_cells": q_count * len(req.models) * variants,
    }


@router.get("/projects/{project_id}/skill-trials")
async def list_skill_trials(project_id: int, limit: int = Query(default=200, ge=1, le=1000)):
    conn = db.init.get_db()
    _require_project(conn, project_id)
    rows = conn.execute(
        "SELECT * FROM skill_trials WHERE project_id = ? ORDER BY id DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [_format_trial(r) for r in rows]


@router.get("/projects/{project_id}/skill-trials/{trial_id}")
async def get_skill_trial(project_id: int, trial_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT * FROM skill_trials WHERE id = ? AND project_id = ?", (trial_id, project_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    out = _format_trial(row)
    out["matrix"] = aggregate_trial_matrix(conn, trial_id)
    if row["skill_id"]:
        skill = conn.execute("SELECT * FROM skills WHERE id = ?", (row["skill_id"],)).fetchone()
        out["skill"] = _format_skill(skill) if skill else None
    return out


@router.get("/projects/{project_id}/skill-trials/{trial_id}/progress")
async def skill_trial_progress(project_id: int, trial_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT status, error_message FROM skill_trials WHERE id = ? AND project_id = ?",
        (trial_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    prog = skill_trial_runs.snapshot_progress(trial_id)
    if prog is None:
        return {"phase": row["status"], "error": row["error_message"]}
    return prog


@router.post("/projects/{project_id}/skill-trials/{trial_id}/cancel")
async def cancel_skill_trial(project_id: int, trial_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id, status FROM skill_trials WHERE id = ? AND project_id = ?",
        (trial_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    event = skill_trial_runs.get_cancel_event(trial_id)
    if event is None:
        raise HTTPException(status_code=409, detail="Trial is not running")
    event.set()
    return {"detail": "Cancellation requested"}


@router.get("/projects/{project_id}/skill-trials/{trial_id}/results")
async def skill_trial_results(
    project_id: int,
    trial_id: int,
    model: str | None = None,
    variant: str | None = Query(default=None, pattern="^(skill|baseline)$"),
    limit: int = Query(default=500, ge=1, le=2000),
):
    conn = db.init.get_db()
    trial = conn.execute(
        "SELECT id FROM skill_trials WHERE id = ? AND project_id = ?", (trial_id, project_id)
    ).fetchone()
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")

    sql = """SELECT str.*, tq.question, tq.reference_answer
             FROM skill_trial_results str
             JOIN test_questions tq ON tq.id = str.test_question_id
             WHERE str.trial_id = ?"""
    params: list = [trial_id]
    if model:
        sql += " AND str.model = ?"
        params.append(model)
    if variant == "skill":
        sql += " AND str.skill_id IS NOT NULL"
    elif variant == "baseline":
        sql += " AND str.skill_id IS NULL"
    sql += " ORDER BY str.test_question_id, str.model LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": r["id"],
            "model": r["model"],
            "variant": "skill" if r["skill_id"] else "baseline",
            "question_id": r["test_question_id"],
            "question": r["question"],
            "response": r["response"],
            "scores": json.loads(r["scores_json"]) if r["scores_json"] else {},
            "directive_results": json.loads(r["directive_results_json"]) if r["directive_results_json"] else [],
            "trace": json.loads(r["trace_json"]) if r["trace_json"] else [],
            "tokens_in": r["tokens_in"],
            "tokens_out": r["tokens_out"],
            "latency_ms": r["latency_ms"],
            "error": r["error"],
        }
        for r in rows
    ]


# --- Apply winning model -------------------------------------------------------


@router.post("/projects/{project_id}/apply-model")
async def apply_preferred_model(project_id: int, req: ApplyModelRequest):
    """Persist the user's chosen model as the project's preferred model.

    Downstream config forms (RAG config, experiments, judges) read this as
    their default suggestion.
    """
    conn = db.init.get_db()
    _require_project(conn, project_id)
    conn.execute(
        f"UPDATE projects SET preferred_model = ?, updated_at = {NOW_SQL} WHERE id = ?",
        (req.model, project_id),
    )
    conn.commit()
    return {"detail": "Preferred model updated", "preferred_model": req.model}
