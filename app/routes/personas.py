"""Persona CRUD and generation routes."""

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db.init
from config import PERSONA_SUBPROCESS_TIMEOUT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["personas"])

# In-memory registry for long-running full-mode persona generation.
# project_id → {"status": "generating"|"completed"|"error", "personas": [...], "detail": ""}
_persona_tasks: dict[int, dict] = {}
_persona_task_lock = threading.Lock()


def _run_persona_subprocess(
    project_id: int,
    chunks_path: str,
    num_personas: int,
    project_dir: str,
    script: str,
) -> None:
    """Run in a daemon thread — writes result into _persona_tasks when done."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, project_dir, chunks_path, str(num_personas), str(project_id)],
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            timeout=PERSONA_SUBPROCESS_TIMEOUT,
            env={**__import__("os").environ},
        )
        if result.returncode != 0:
            raise RuntimeError("KG persona generation subprocess exited non-zero (check server logs)")
        personas = json.loads(result.stdout.strip().split("\n")[-1])
        with _persona_task_lock:
            _persona_tasks[project_id] = {"status": "completed", "personas": personas}
    except Exception as exc:
        logger.error("Full persona generation failed for project %d: %s", project_id, exc)
        with _persona_task_lock:
            _persona_tasks[project_id] = {"status": "error", "detail": str(exc)}
    finally:
        Path(chunks_path).unlink(missing_ok=True)


class PersonaCreate(BaseModel):
    name: str
    role_description: str
    question_style: str = ""


class PersonaUpdate(BaseModel):
    name: str | None = None
    role_description: str | None = None
    question_style: str | None = None


class PersonaGenerateRequest(BaseModel):
    chunk_config_id: int
    num_personas: int = 3
    mode: str = "fast"  # "fast" or "full"


# --- CRUD ---


@router.get("/projects/{project_id}/personas")
async def list_personas(project_id: int):
    conn = db.init.get_db()
    if conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT id, name, role_description, question_style, created_at "
        "FROM personas WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return {
        "personas": [
            {
                "id": r["id"],
                "name": r["name"],
                "role_description": r["role_description"],
                "question_style": r["question_style"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.post("/projects/{project_id}/personas", status_code=201)
async def create_persona(project_id: int, req: PersonaCreate):
    conn = db.init.get_db()
    # Validate project exists
    if conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    cursor = conn.execute(
        "INSERT INTO personas (project_id, name, role_description, question_style) VALUES (?, ?, ?, ?)",
        (project_id, req.name, req.role_description, req.question_style),
    )
    conn.commit()
    return {
        "id": cursor.lastrowid,
        "name": req.name,
        "role_description": req.role_description,
        "question_style": req.question_style,
    }


@router.post("/projects/{project_id}/personas/bulk", status_code=201)
async def save_personas_bulk(project_id: int, personas: list[PersonaCreate]):
    """Save multiple personas at once (e.g. after auto-generation)."""
    conn = db.init.get_db()
    if conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    saved = []
    try:
        for p in personas:
            cursor = conn.execute(
                "INSERT INTO personas (project_id, name, role_description, question_style) VALUES (?, ?, ?, ?)",
                (project_id, p.name, p.role_description, p.question_style),
            )
            saved.append({
                "id": cursor.lastrowid,
                "name": p.name,
                "role_description": p.role_description,
                "question_style": p.question_style,
            })
        conn.commit()
    except Exception:
        conn.commit()  # leave connection in clean state
        raise
    return {"personas": saved}


@router.put("/projects/{project_id}/personas/{persona_id}")
async def update_persona(project_id: int, persona_id: int, req: PersonaUpdate):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id FROM personas WHERE id = ? AND project_id = ?",
        (persona_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Map allowed Pydantic fields to their column names (whitelist).
    allowed_columns = {
        "name": req.name,
        "role_description": req.role_description,
        "question_style": req.question_style,
    }
    updates = []
    values = []
    for col, val in allowed_columns.items():
        if val is not None:
            updates.append(f"{col} = ?")
            values.append(val)

    if updates:
        values.append(persona_id)
        sql = "UPDATE personas SET " + ", ".join(updates) + " WHERE id = ?"
        conn.execute(sql, values)
        conn.commit()

    return {"detail": "updated"}


@router.delete("/projects/{project_id}/personas/{persona_id}")
async def delete_persona(project_id: int, persona_id: int):
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id FROM personas WHERE id = ? AND project_id = ?",
        (persona_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")

    conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    conn.commit()
    return {"detail": "deleted"}


# --- Generation ---


@router.post("/projects/{project_id}/generate-personas")
async def generate_project_personas(project_id: int, req: PersonaGenerateRequest):
    conn = db.init.get_db()

    # Validate chunk config belongs to project
    cc = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if cc is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    chunk_rows = conn.execute(
        "SELECT content FROM chunks WHERE chunk_config_id = ?",
        (req.chunk_config_id,),
    ).fetchall()
    if not chunk_rows:
        raise HTTPException(
            status_code=422,
            detail="No chunks found for this config. Generate chunks first.",
        )

    chunks = [r["content"] for r in chunk_rows]

    if req.mode == "full":
        # Check for a task already running for this project
        with _persona_task_lock:
            existing = _persona_tasks.get(project_id)
            if existing and existing["status"] == "generating":
                raise HTTPException(status_code=409, detail="Persona generation already in progress for this project")
            _persona_tasks[project_id] = {"status": "generating"}

        script = (
            "import json, sys, os; "
            "os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1]); "
            "print('SUBPROCESS STARTED, OPENAI_API_KEY set:', bool(os.environ.get('OPENAI_API_KEY')), file=sys.stderr); "
            "chunks = json.loads(open(sys.argv[2]).read()); "
            "print(f'Loaded {len(chunks)} chunks', file=sys.stderr); "
            "from evaluation.metrics.testgen import generate_personas, _enrich_with_question_styles; "
            "personas = generate_personas(chunks=chunks, num_personas=int(sys.argv[3]), fast=False, project_id=int(sys.argv[4])); "
            "print(json.dumps(_enrich_with_question_styles(personas)))"
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(chunks, f)
            chunks_path = f.name

        project_dir = str(Path(__file__).resolve().parents[2])

        t = threading.Thread(
            target=_run_persona_subprocess,
            args=(project_id, chunks_path, req.num_personas, project_dir, script),
            daemon=True,
        )
        t.start()

        # Return immediately — client polls /generate-personas/status
        return {"status": "generating"}
    else:
        from evaluation.metrics.testgen import generate_personas_fast

        personas = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: generate_personas_fast(
                chunks=chunks,
                num_personas=req.num_personas,
            ),
        )
        return {"status": "completed", "personas": personas}


@router.get("/projects/{project_id}/generate-personas/status")
async def get_persona_generation_status(project_id: int):
    """Poll for the result of a full-mode persona generation task.

    Returns:
      {"status": "generating"}                         — still running
      {"status": "completed", "personas": [...]}       — done (entry cleared after read)
      {"status": "error", "detail": "..."}             — failed
    """
    with _persona_task_lock:
        task = _persona_tasks.get(project_id)
    if task is None:
        raise HTTPException(status_code=404, detail="No persona generation task found for this project")
    if task["status"] == "completed":
        # Clear after read so a new generation can start cleanly
        with _persona_task_lock:
            _persona_tasks.pop(project_id, None)
    return task
