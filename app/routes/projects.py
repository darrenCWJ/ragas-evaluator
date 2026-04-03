"""Project CRUD, external baselines, and API config routes."""

import csv
import io
import sqlite3

from fastapi import APIRouter, HTTPException, UploadFile, File

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
            "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Project name already exists")


@router.get("/projects")
async def list_projects():
    conn = db.init.get_db()
    rows = conn.execute(
        "SELECT id, name, description, created_at, updated_at FROM projects"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/projects/{project_id}")
async def get_project(project_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return dict(row)


@router.put("/projects/{project_id}")
async def update_project(project_id: int, req: ProjectUpdate):
    if req.name is None and req.description is None:
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
    updates.append("updated_at = CURRENT_TIMESTAMP")
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
        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    return dict(row)


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


@router.post("/projects/{project_id}/baselines/upload-csv", status_code=201)
async def upload_baseline_csv(project_id: int, file: UploadFile = File(...)):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    if len(content) > MAX_BASELINE_CSV_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum 10MB.")

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode file as UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(
            status_code=400, detail="CSV file is empty or has no headers"
        )

    lower_fields = [f.strip().lower() for f in reader.fieldnames]
    if "question" not in lower_fields or "answer" not in lower_fields:
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have 'question' and 'answer' columns. Found: {', '.join(reader.fieldnames)}",
        )

    col_map = {}
    for orig, low in zip(reader.fieldnames, lower_fields):
        if low == "question":
            col_map["question"] = orig
        elif low == "answer":
            col_map["answer"] = orig
        elif low in ("sources", "source", "context", "contexts"):
            col_map["sources"] = orig

    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_BASELINE_ROWS:
            break
        q = _sanitize_csv_value(row.get(col_map["question"], ""))
        a = _sanitize_csv_value(row.get(col_map["answer"], ""))
        if not q or not a:
            continue
        s = _sanitize_csv_value(row.get(col_map.get("sources", ""), "") or "")
        rows.append((project_id, q, a, s, "csv"))

    if not rows:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    conn.executemany(
        "INSERT INTO external_baselines (project_id, question, answer, sources, source_type) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    return {
        "imported": len(rows),
        "preview": [
            {"question": r[1], "answer": r[2], "sources": r[3]} for r in rows[:5]
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
        "SELECT id, project_id, question, answer, sources, source_type, created_at "
        "FROM external_baselines WHERE project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()

    return [
        {
            "id": r[0],
            "project_id": r[1],
            "question": r[2],
            "answer": r[3],
            "sources": r[4],
            "source_type": r[5],
            "created_at": r[6],
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
            "UPDATE api_configs SET endpoint_url = ?, api_key = ?, headers_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
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
