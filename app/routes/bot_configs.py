"""Bot config CRUD routes."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models import BotConfigCreate, BotConfigUpdate
import db.init

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["bot_configs"])


def _parse_bot_config_row(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "connector_type": row["connector_type"],
        "config_json": json.loads(row["config_json"]) if row["config_json"] else {},
        "prompt_for_sources": bool(row["prompt_for_sources"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.post("/projects/{project_id}/bot-configs", status_code=201)
async def create_bot_config(project_id: int, req: BotConfigCreate):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    cursor = conn.execute(
        """INSERT INTO bot_configs (project_id, name, connector_type, config_json, prompt_for_sources)
           VALUES (?, ?, ?, ?, ?)""",
        (
            project_id,
            req.name,
            req.connector_type,
            json.dumps(req.config_json),
            req.prompt_for_sources,
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM bot_configs WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _parse_bot_config_row(row)


@router.get("/projects/{project_id}/bot-configs")
async def list_bot_configs(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM bot_configs WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [_parse_bot_config_row(r) for r in rows]


@router.get("/projects/{project_id}/bot-configs/{config_id}")
async def get_bot_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM bot_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Bot config not found")

    return _parse_bot_config_row(row)


@router.put("/projects/{project_id}/bot-configs/{config_id}")
async def update_bot_config(project_id: int, config_id: int, req: BotConfigUpdate):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM bot_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Bot config not found")

    updates: list[str] = []
    params: list = []
    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name)
    if req.connector_type is not None:
        updates.append("connector_type = ?")
        params.append(req.connector_type)
    if req.config_json is not None:
        updates.append("config_json = ?")
        params.append(json.dumps(req.config_json))
    if req.prompt_for_sources is not None:
        updates.append("prompt_for_sources = ?")
        params.append(req.prompt_for_sources)

    if not updates:
        return _parse_bot_config_row(row)

    updates.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(config_id)

    conn.execute(
        f"UPDATE bot_configs SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM bot_configs WHERE id = ?", (config_id,)
    ).fetchone()
    return _parse_bot_config_row(updated)


@router.delete("/projects/{project_id}/bot-configs/{config_id}", status_code=204)
async def delete_bot_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM bot_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Bot config not found")

    conn.execute("DELETE FROM bot_configs WHERE id = ?", (config_id,))
    conn.commit()
    return None
