"""Project CRUD, external baselines, and API config routes."""

import csv
import io
import sqlite3

import json

from fastapi import APIRouter, Form, HTTPException, UploadFile, File

from app.models import (
    ApiConfigCreate,
    ProjectCreate,
    ProjectUpdate,
    MAX_BASELINE_CSV_SIZE,
    MAX_BASELINE_ROWS,
)
import db.init

router = APIRouter(prefix="/api", tags=["projects"])


# --- Project CRUD ---


@router.post("/projects", status_code=201)
async def create_project(req: ProjectCreate):
    conn = db.init.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (req.name, req.description),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name, description, created_at, updated_at, judge_model_assignments_json FROM projects WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _format_project(row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Project name already exists")


def _format_project(row) -> dict:
    result = dict(row)
    raw = result.pop("judge_model_assignments_json", None)
    result["judge_model_assignments"] = json.loads(raw) if raw else None
    return result


@router.get("/projects")
async def list_projects():
    conn = db.init.get_db()
    rows = conn.execute(
        "SELECT id, name, description, created_at, updated_at, judge_model_assignments_json FROM projects"
    ).fetchall()
    return [_format_project(r) for r in rows]


@router.get("/projects/{project_id}")
async def get_project(project_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id, name, description, created_at, updated_at, judge_model_assignments_json FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _format_project(row)


@router.put("/projects/{project_id}")
async def update_project(project_id: int, req: ProjectUpdate):
    if req.name is None and req.description is None and req.judge_model_assignments is None:
        raise HTTPException(status_code=400, detail="No fields to update")
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = []
    params = []
    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name)
    if req.description is not None:
        updates.append("description = ?")
        params.append(req.description)
    if req.judge_model_assignments is not None:
        updates.append("judge_model_assignments_json = ?")
        params.append(json.dumps(req.judge_model_assignments) if req.judge_model_assignments else None)
    updates.append("updated_at = datetime('now', 'localtime')")
    params.append(project_id)
    try:
        conn.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Project name already exists")
    row = conn.execute(
        "SELECT id, name, description, created_at, updated_at, judge_model_assignments_json FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    return _format_project(row)


@router.get("/judge-models")
async def list_judge_models():
    """Return all judge-eligible models with API key availability."""
    from pipeline.llm import get_available_judge_models
    return {"models": get_available_judge_models()}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return {"detail": "Project deleted"}


# --- External Baselines ---


def _sanitize_csv_value(val: str) -> str:
    """Strip whitespace and prevent CSV injection."""
    val = val.strip()
    if val and val[0] in ("=", "+", "-", "@"):
        val = "'" + val
    return val


def _parse_csv_text(content: bytes) -> tuple[str, csv.DictReader]:
    """Decode CSV bytes and return (text, DictReader). Raises HTTPException on failure."""
    if len(content) > MAX_BASELINE_CSV_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum 10MB.")
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode file as UTF-8")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no headers")
    return text, reader


@router.post("/projects/{project_id}/baselines/preview-csv")
async def preview_baseline_csv(project_id: int, file: UploadFile = File(...)):
    """Return CSV headers and first 5 rows so the frontend can show column mapping."""
    conn = db.init.get_db()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    text, reader = _parse_csv_text(content)

    headers = list(reader.fieldnames)
    preview_rows = []
    for i, row in enumerate(reader):
        if i >= 5:
            break
        preview_rows.append({h: row.get(h, "") for h in headers})

    return {"headers": headers, "rows": preview_rows}


@router.post("/projects/{project_id}/baselines/upload-csv", status_code=201)
async def upload_baseline_csv(
    project_id: int,
    file: UploadFile = File(...),
    question_col: str = Form(...),
    answer_col: str = Form(...),
    reference_answer_col: str = Form(""),
    context_col: str = Form(""),
    config_name: str = Form(""),
):
    """Upload CSV with user-specified column mapping. Creates a bot_config (type=csv).

    Columns:
      - question_col: the test question (required)
      - answer_col: the bot's actual answer (required)
      - reference_answer_col: the expected/ground-truth answer (optional — defaults to answer_col)
      - context_col: source data / context (optional)
    """
    conn = db.init.get_db()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    text, reader = _parse_csv_text(content)

    headers = list(reader.fieldnames)
    if question_col not in headers:
        raise HTTPException(status_code=400, detail=f"Question column '{question_col}' not found in CSV headers")
    if answer_col not in headers:
        raise HTTPException(status_code=400, detail=f"Answer column '{answer_col}' not found in CSV headers")
    if reference_answer_col and reference_answer_col not in headers:
        raise HTTPException(status_code=400, detail=f"Reference answer column '{reference_answer_col}' not found in CSV headers")
    if context_col and context_col not in headers:
        raise HTTPException(status_code=400, detail=f"Context column '{context_col}' not found in CSV headers")

    has_contexts = bool(context_col)
    has_reference = bool(reference_answer_col)

    # Create bot_config entry
    bot_name = config_name.strip() if config_name.strip() else (file.filename or "CSV Upload")
    config_json_data = {
        "bot_config_id": 0,  # placeholder, updated after insert
        "has_contexts": has_contexts,
        "has_reference_answer": has_reference,
        "source_file": file.filename,
    }
    cursor = conn.execute(
        """INSERT INTO bot_configs (project_id, name, connector_type, config_json, prompt_for_sources)
           VALUES (?, ?, 'csv', ?, FALSE)""",
        (project_id, bot_name, json.dumps(config_json_data)),
    )
    bot_config_id = cursor.lastrowid

    # Update config_json with the actual bot_config_id
    config_json_data["bot_config_id"] = bot_config_id
    conn.execute(
        "UPDATE bot_configs SET config_json = ? WHERE id = ?",
        (json.dumps(config_json_data), bot_config_id),
    )
    conn.commit()

    # Parse and insert rows
    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_BASELINE_ROWS:
            break
        q = _sanitize_csv_value(row.get(question_col, ""))
        a = _sanitize_csv_value(row.get(answer_col, ""))
        if not q or not a:
            continue
        ref = _sanitize_csv_value(row.get(reference_answer_col, "") or "") if reference_answer_col else ""
        s = _sanitize_csv_value(row.get(context_col, "") or "") if context_col else ""
        rows.append((project_id, bot_config_id, q, a, ref, s, "csv"))

    if not rows:
        # Clean up the bot_config if no valid rows
        conn.execute("DELETE FROM bot_configs WHERE id = ?", (bot_config_id,))
        conn.commit()
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    conn.executemany(
        "INSERT INTO external_baselines (project_id, bot_config_id, question, answer, reference_answer, sources, source_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    return {
        "imported": len(rows),
        "bot_config_id": bot_config_id,
        "preview": [
            {"question": r[2], "answer": r[3], "reference_answer": r[4], "sources": r[5]} for r in rows[:5]
        ],
    }


@router.get("/projects/{project_id}/baselines")
async def list_baselines(project_id: int):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT id, project_id, question, answer, reference_answer, sources, source_type, created_at "
        "FROM external_baselines WHERE project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()

    return [
        {
            "id": r["id"],
            "project_id": r["project_id"],
            "question": r["question"],
            "answer": r["answer"],
            "reference_answer": r["reference_answer"] or "",
            "sources": r["sources"] or "",
            "source_type": r["source_type"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.delete("/projects/{project_id}/baselines/{baseline_id}")
async def delete_baseline(project_id: int, baseline_id: int):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM external_baselines WHERE id = ? AND project_id = ?",
        (baseline_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
    conn.execute("DELETE FROM external_baselines WHERE id = ?", (baseline_id,))
    conn.commit()
    return {"detail": "Baseline deleted"}


@router.delete("/projects/{project_id}/baselines")
async def clear_baselines(project_id: int):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conn.execute("DELETE FROM external_baselines WHERE project_id = ?", (project_id,))
    conn.commit()
    return {"detail": "All baselines cleared"}


# --- API Config ---


def _redact_key(key: str | None) -> str | None:
    if key is None:
        return None
    if len(key) <= 4:
        return "****"
    return f"****{key[-4:]}"


@router.post("/projects/{project_id}/api-config", status_code=201)
async def save_api_config(project_id: int, payload: ApiConfigCreate):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = conn.execute(
        "SELECT id FROM api_configs WHERE project_id = ?", (project_id,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE api_configs SET endpoint_url = ?, api_key = ?, headers_json = ?, updated_at = datetime('now', 'localtime') WHERE project_id = ?",
            (payload.endpoint_url, payload.api_key, payload.headers_json, project_id),
        )
        config_id = existing[0]
    else:
        cur = conn.execute(
            "INSERT INTO api_configs (project_id, endpoint_url, api_key, headers_json) VALUES (?, ?, ?, ?)",
            (project_id, payload.endpoint_url, payload.api_key, payload.headers_json),
        )
        config_id = cur.lastrowid

    conn.commit()

    row = conn.execute(
        "SELECT id, project_id, endpoint_url, api_key, headers_json, created_at, updated_at FROM api_configs WHERE id = ?",
        (config_id,),
    ).fetchone()

    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "endpoint_url": row["endpoint_url"],
        "api_key": _redact_key(row["api_key"]),
        "headers_json": row["headers_json"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/projects/{project_id}/api-config")
async def get_api_config(project_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id, project_id, endpoint_url, api_key, headers_json, created_at, updated_at FROM api_configs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No API config found for this project"
        )
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "endpoint_url": row["endpoint_url"],
        "api_key": _redact_key(row["api_key"]),
        "headers_json": row["headers_json"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.delete("/projects/{project_id}/api-config")
async def delete_api_config(project_id: int):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM api_configs WHERE project_id = ?", (project_id,)
    ).fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404, detail="No API config found for this project"
        )
    conn.execute("DELETE FROM api_configs WHERE project_id = ?", (project_id,))
    conn.commit()
    return {"detail": "API config deleted"}
