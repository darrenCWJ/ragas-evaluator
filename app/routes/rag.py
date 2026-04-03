"""RAG config CRUD and query routes."""

import json

from fastapi import APIRouter, HTTPException

from app.models import RagConfigCreate, RagConfigUpdate, RagQueryRequest
import db.init
from pipeline.rag import single_shot_query, multi_step_query

router = APIRouter(prefix="/api", tags=["rag"])


def _parse_rag_config_row(row) -> dict:
    d = dict(row)
    lpj = d.pop("llm_params_json", None)
    d["llm_params"] = json.loads(lpj) if lpj else None
    return d


def _expand_rag_config(rag_row, conn) -> dict:
    d = _parse_rag_config_row(rag_row)

    chunk_row = conn.execute(
        "SELECT name, method, params_json FROM chunk_configs WHERE id = ?",
        (d["chunk_config_id"],),
    ).fetchone()
    if chunk_row:
        d["chunk_config"] = dict(chunk_row)
    else:
        d["chunk_config"] = None

    emb_row = conn.execute(
        "SELECT name, type, model_name FROM embedding_configs WHERE id = ?",
        (d["embedding_config_id"],),
    ).fetchone()
    if emb_row:
        d["embedding_config"] = dict(emb_row)
    else:
        d["embedding_config"] = None

    return d


# ------------------------------------------------------------------
# List routes (registered before parameterised routes to avoid
# path conflicts with /{config_id}).
# ------------------------------------------------------------------


@router.get("/projects/{project_id}/rag-configs")
async def list_rag_configs(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM rag_configs WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [_parse_rag_config_row(r) for r in rows]


@router.get("/projects/{project_id}/rag-configs/expanded")
async def list_rag_configs_expanded(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM rag_configs WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [_expand_rag_config(r, conn) for r in rows]


@router.get("/projects/{project_id}/rag-configs/{config_id}/expanded")
async def get_rag_config_expanded(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="RAG config not found")
    return _expand_rag_config(row, conn)


@router.get("/projects/{project_id}/rag-configs/{config_id}")
async def get_rag_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="RAG config not found")
    return _parse_rag_config_row(row)


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------


@router.post("/projects/{project_id}/rag-configs", status_code=201)
async def create_rag_config(project_id: int, body: RagConfigCreate):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    emb = conn.execute(
        "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
        (body.embedding_config_id, project_id),
    ).fetchone()
    if emb is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")

    chunk = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (body.chunk_config_id, project_id),
    ).fetchone()
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    if body.search_type == "hybrid":
        if body.sparse_config_id is None:
            raise HTTPException(
                status_code=400,
                detail="sparse_config_id is required for hybrid search",
            )
        sparse = conn.execute(
            "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
            (body.sparse_config_id, project_id),
        ).fetchone()
        if sparse is None:
            raise HTTPException(status_code=404, detail="Sparse config not found")

    cursor = conn.execute(
        """INSERT INTO rag_configs
           (project_id, name, embedding_config_id, chunk_config_id,
            search_type, sparse_config_id, alpha, llm_model,
            llm_params_json, top_k, system_prompt, response_mode, max_steps)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            body.name,
            body.embedding_config_id,
            body.chunk_config_id,
            body.search_type,
            body.sparse_config_id,
            body.alpha,
            body.llm_model,
            json.dumps(body.llm_params) if body.llm_params else None,
            body.top_k,
            body.system_prompt,
            body.response_mode,
            body.max_steps,
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _parse_rag_config_row(row)


# ------------------------------------------------------------------
# Update
# ------------------------------------------------------------------


@router.put("/projects/{project_id}/rag-configs/{config_id}")
async def update_rag_config(
    project_id: int, config_id: int, body: RagConfigUpdate
):
    conn = db.init.get_db()

    existing = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="RAG config not found")

    # Validate FK references when provided
    if body.embedding_config_id is not None:
        emb = conn.execute(
            "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
            (body.embedding_config_id, project_id),
        ).fetchone()
        if emb is None:
            raise HTTPException(status_code=404, detail="Embedding config not found")

    if body.chunk_config_id is not None:
        chunk = conn.execute(
            "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
            (body.chunk_config_id, project_id),
        ).fetchone()
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk config not found")

    # Determine effective search_type for hybrid validation
    effective_search_type = (
        body.search_type if body.search_type is not None else existing["search_type"]
    )

    if effective_search_type == "hybrid":
        effective_sparse = (
            body.sparse_config_id
            if body.sparse_config_id is not None
            else existing["sparse_config_id"]
        )
        if effective_sparse is None:
            raise HTTPException(
                status_code=400,
                detail="sparse_config_id is required for hybrid search",
            )
        sparse = conn.execute(
            "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
            (effective_sparse, project_id),
        ).fetchone()
        if sparse is None:
            raise HTTPException(status_code=404, detail="Sparse config not found")

    # Build SET clause from non-None fields
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.embedding_config_id is not None:
        updates["embedding_config_id"] = body.embedding_config_id
    if body.chunk_config_id is not None:
        updates["chunk_config_id"] = body.chunk_config_id
    if body.search_type is not None:
        updates["search_type"] = body.search_type
    if body.llm_model is not None:
        updates["llm_model"] = body.llm_model
    if body.top_k is not None:
        updates["top_k"] = body.top_k
    if body.system_prompt is not None:
        updates["system_prompt"] = body.system_prompt
    if body.llm_params is not None:
        updates["llm_params_json"] = json.dumps(body.llm_params)
    if body.sparse_config_id is not None:
        updates["sparse_config_id"] = body.sparse_config_id
    if body.alpha is not None:
        updates["alpha"] = body.alpha
    if body.response_mode is not None:
        updates["response_mode"] = body.response_mode
    if body.max_steps is not None:
        updates["max_steps"] = body.max_steps

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [config_id, project_id]
        conn.execute(
            f"UPDATE rag_configs SET {set_clause} WHERE id = ? AND project_id = ?",
            values,
        )
        conn.commit()

    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ?", (config_id,)
    ).fetchone()
    return _parse_rag_config_row(row)


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


@router.delete("/projects/{project_id}/rag-configs/{config_id}")
async def delete_rag_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    existing = conn.execute(
        "SELECT id FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="RAG config not found")

    # Detach experiments referencing this config before deleting
    conn.execute(
        "UPDATE experiments SET rag_config_id = NULL WHERE rag_config_id = ?",
        (config_id,),
    )
    conn.execute("DELETE FROM rag_configs WHERE id = ?", (config_id,))
    conn.commit()
    return {"detail": "RAG config deleted"}


# ------------------------------------------------------------------
# Query
# ------------------------------------------------------------------


@router.post("/projects/{project_id}/rag-configs/{config_id}/query")
async def rag_query(project_id: int, config_id: int, body: RagQueryRequest):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="RAG config not found")

    if row["response_mode"] == "multi_step":
        return await multi_step_query(body.query, row, conn)
    return await single_shot_query(body.query, row, conn)
