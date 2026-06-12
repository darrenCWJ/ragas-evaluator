"""Tool definition CRUD for agentic experiments."""

import json
import logging
import re

from fastapi import APIRouter, HTTPException

import db.init
from app.models import ToolDefinitionCreate
from pipeline.tools import BUILTIN_TOOLS, VALID_TOOL_MODES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tools"])

_TOOL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["parameters"] = json.loads(d.pop("parameters_json") or "{}")
    fixtures = d.pop("fixtures_json", None)
    d["fixtures"] = json.loads(fixtures) if fixtures else None
    return d


@router.get("/tools/builtins")
async def list_builtin_tools():
    """Available builtin tool implementations (templates for tool definitions)."""
    return {
        "builtins": [
            {"name": name, **spec} for name, spec in BUILTIN_TOOLS.items()
        ]
    }


@router.get("/projects/{project_id}/tools")
async def list_tools(project_id: int):
    conn = db.init.get_db()
    rows = conn.execute(
        "SELECT * FROM tool_definitions WHERE project_id = ? ORDER BY name",
        (project_id,),
    ).fetchall()
    return {"tools": [_row_to_dict(r) for r in rows]}


@router.post("/projects/{project_id}/tools", status_code=201)
async def create_tool(project_id: int, req: ToolDefinitionCreate):
    conn = db.init.get_db()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not _TOOL_NAME_RE.match(req.name):
        raise HTTPException(
            status_code=422,
            detail="Tool name must be a valid identifier (letters, digits, underscores; max 64 chars)",
        )
    if req.mode not in VALID_TOOL_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(VALID_TOOL_MODES)}")
    if req.mode == "builtin" and req.builtin_name not in BUILTIN_TOOLS:
        raise HTTPException(
            status_code=422,
            detail=f"builtin_name must be one of {sorted(BUILTIN_TOOLS)}",
        )
    parameters = req.parameters or {"type": "object", "properties": {}}

    try:
        cursor = conn.execute(
            """INSERT INTO tool_definitions
               (project_id, name, description, parameters_json, mode, fixtures_json, builtin_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                req.name,
                req.description,
                json.dumps(parameters),
                req.mode,
                json.dumps(req.fixtures) if req.fixtures else None,
                req.builtin_name,
            ),
        )
        conn.commit()
    except Exception as e:
        if db.init.is_integrity_error(e):
            raise HTTPException(status_code=409, detail=f"A tool named '{req.name}' already exists") from e
        raise

    row = conn.execute(
        "SELECT * FROM tool_definitions WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_dict(row)


@router.delete("/projects/{project_id}/tools/{tool_id}", status_code=204)
async def delete_tool(project_id: int, tool_id: int):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM tool_definitions WHERE id = ? AND project_id = ?",
        (tool_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    conn.execute("DELETE FROM tool_definitions WHERE id = ?", (tool_id,))
    conn.commit()
    return None
