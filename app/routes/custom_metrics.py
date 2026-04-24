"""CRUD routes for user-defined custom evaluation metrics."""

import json
import logging

from fastapi import APIRouter, HTTPException

from app.models import CustomMetricCreate, RefinementRequest
from evaluation.scoring import ALL_METRICS
import db.init
from pipeline.llm import chat_completion
from config import DEFAULT_EVAL_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["custom_metrics"])

_REFINEMENT_SYSTEM = """\
You are an expert evaluation engineer designing rubrics for LLM judges.

Given a metric description from a user, produce a concise, actionable system prompt \
that an LLM evaluator will use to assess chatbot responses.

The output prompt must:
- Define the criterion precisely in 1-2 sentences
- Specify three verdict levels with concrete distinguishing conditions:
    good: response clearly meets the criterion
    mixed: response partially meets the criterion or has notable inconsistencies
    bad: response clearly fails the criterion
- Tell the evaluator exactly what granularity to use when quoting evidence from the response:
    individual sentences for factual claims, safety issues, or citation checks
    representative phrases for tone, style, or register assessments
    structural description for completeness, length, or verbosity evaluations
- Keep the total length under 400 words

Output ONLY the evaluation system prompt as plain text — no JSON, no preamble, no explanation."""

_REFINEMENT_USER = """\
Metric description: {description}

Write the LLM evaluation system prompt for this metric."""


def _parse_custom_metric_row(row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "metric_type": row["metric_type"],
        "prompt": row["prompt"],
        "rubrics": json.loads(row["rubrics_json"]) if row["rubrics_json"] else None,
        "min_score": row["min_score"],
        "max_score": row["max_score"],
        "refined_prompt": row["refined_prompt"] if "refined_prompt" in keys else None,
        "few_shot_examples": json.loads(row["few_shot_examples_json"]) if "few_shot_examples_json" in keys and row["few_shot_examples_json"] else None,
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


@router.post("/projects/{project_id}/custom-metrics/refine-description")
async def refine_metric_description(project_id: int, req: RefinementRequest):
    """Use an LLM to transform a plain-language metric description into a structured evaluation prompt."""
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    messages = [
        {"role": "system", "content": _REFINEMENT_SYSTEM},
        {"role": "user", "content": _REFINEMENT_USER.format(description=req.description)},
    ]
    try:
        result = await chat_completion(DEFAULT_EVAL_MODEL, messages, {"temperature": 0.3})
        refined = result["content"].strip()
    except Exception as e:
        logger.error("Failed to refine metric description: %s", e)
        raise HTTPException(status_code=502, detail="Failed to refine description via LLM")

    return {"refined_prompt": refined}


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
           (project_id, name, metric_type, prompt, rubrics_json, min_score, max_score, refined_prompt, few_shot_examples_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            req.name,
            req.metric_type,
            req.prompt,
            json.dumps(req.rubrics) if req.rubrics else None,
            req.min_score,
            req.max_score,
            req.refined_prompt,
            json.dumps(req.few_shot_examples) if req.few_shot_examples else None,
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM custom_metrics WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _parse_custom_metric_row(row)


@router.put("/projects/{project_id}/custom-metrics/{metric_id}")
async def update_custom_metric(project_id: int, metric_id: int, req: CustomMetricCreate):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT * FROM custom_metrics WHERE id = ? AND project_id = ?",
        (metric_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Custom metric not found")

    conn.execute(
        """UPDATE custom_metrics
           SET metric_type = ?, prompt = ?, rubrics_json = ?, min_score = ?, max_score = ?,
               refined_prompt = ?, few_shot_examples_json = ?
           WHERE id = ?""",
        (
            req.metric_type,
            req.prompt,
            json.dumps(req.rubrics) if req.rubrics else None,
            req.min_score,
            req.max_score,
            req.refined_prompt,
            json.dumps(req.few_shot_examples) if req.few_shot_examples else None,
            metric_id,
        ),
    )
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM custom_metrics WHERE id = ?", (metric_id,)
    ).fetchone()
    return _parse_custom_metric_row(updated)


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
