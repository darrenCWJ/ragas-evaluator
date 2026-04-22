"""Bot config CRUD routes."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models import BotConfigCreate, BotConfigUpdate
import db.init

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["bot_configs"])


def bot_config_returns_contexts(connector_type: str, config_json: dict) -> bool:
    """Determine whether a bot config will return retrieved contexts.

    - Glean always returns structured citations.
    - Custom connectors only return citations when a response_citations_path
      is configured.
    - LLM connectors (openai, claude, deepseek, gemini) never return
      structured retrieved contexts.
    """
    if connector_type == "glean":
        return True
    if connector_type == "custom":
        return bool(config_json.get("response_citations_path"))
    if connector_type == "csv":
        return bool(config_json.get("has_contexts"))
    return False


def _parse_bot_config_row(row) -> dict:
    config = json.loads(row["config_json"]) if row["config_json"] else {}
    safe_config = {
        k: ("***" if k == "api_key" and v else v)
        for k, v in config.items()
    }
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "connector_type": row["connector_type"],
        "config_json": safe_config,
        "prompt_for_sources": bool(row["prompt_for_sources"]),
        "returns_contexts": bot_config_returns_contexts(row["connector_type"], safe_config),
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
    params.append(datetime.now().isoformat())
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


@router.get("/projects/{project_id}/bot-configs/{config_id}/baselines")
async def list_bot_config_baselines(project_id: int, config_id: int, limit: int = 5):
    """Return sample baseline rows for a specific bot config."""
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT id FROM bot_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Bot config not found")

    total = conn.execute(
        "SELECT COUNT(*) FROM external_baselines WHERE bot_config_id = ?",
        (config_id,),
    ).fetchone()[0]

    rows = conn.execute(
        "SELECT id, question, answer, reference_answer, sources, created_at "
        "FROM external_baselines WHERE bot_config_id = ? ORDER BY id LIMIT ?",
        (config_id, min(limit, 50)),
    ).fetchall()

    return {
        "total": total,
        "rows": [
            {
                "id": r["id"],
                "question": r["question"],
                "answer": r["answer"],
                "reference_answer": r["reference_answer"] or "",
                "sources": r["sources"] or "",
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


@router.delete("/projects/{project_id}/bot-configs/{config_id}", status_code=204)
async def delete_bot_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM bot_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Bot config not found")

    # Check referential integrity — cannot delete if experiments reference this bot config
    exp = conn.execute(
        "SELECT id FROM experiments WHERE bot_config_id = ?",
        (config_id,),
    ).fetchone()
    if exp is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete bot config referenced by experiments",
        )

    conn.execute("DELETE FROM bot_configs WHERE id = ?", (config_id,))
    conn.commit()
    return None
