"""Chunk config CRUD and chunk generation routes."""

import json

from fastapi import APIRouter, HTTPException

from app.models import ChunkConfigCreate
from pipeline.chunking import chunk_text_pipeline
import db.init

router = APIRouter(prefix="/api", tags=["chunks"])


def _parse_chunk_config_row(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json"))
    s2m = d.pop("step2_method", None)
    s2p = d.pop("step2_params_json", None)
    d["step2_method"] = s2m
    d["step2_params"] = json.loads(s2p) if s2p else None
    fp = d.pop("filter_params_json", None)
    d["filter_params"] = json.loads(fp) if fp else None
    return d


@router.post("/projects/{project_id}/chunk-configs", status_code=201)
async def create_chunk_config(project_id: int, req: ChunkConfigCreate):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    cursor = conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json, step2_method, step2_params_json, filter_params_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            req.name,
            req.method,
            json.dumps(req.params),
            req.step2_method,
            json.dumps(req.step2_params) if req.step2_params else None,
            json.dumps(req.filter_params) if req.filter_params else None,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _parse_chunk_config_row(row)


@router.get("/projects/{project_id}/chunk-configs")
async def list_chunk_configs(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute(
        "SELECT * FROM chunk_configs WHERE project_id = ?", (project_id,)
    ).fetchall()
    return [_parse_chunk_config_row(r) for r in rows]


@router.get("/projects/{project_id}/chunk-configs/{config_id}")
async def get_chunk_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")
    return _parse_chunk_config_row(row)


@router.delete("/projects/{project_id}/chunk-configs/{config_id}")
async def delete_chunk_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    existing = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")
    rag_refs = conn.execute(
        "SELECT COUNT(*) as cnt FROM rag_configs WHERE chunk_config_id = ?",
        (config_id,),
    ).fetchone()
    if rag_refs["cnt"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Chunk config is referenced by {rag_refs['cnt']} RAG config(s)",
        )
    exp_refs = conn.execute(
        "SELECT COUNT(*) as cnt FROM experiments WHERE chunk_config_id = ?",
        (config_id,),
    ).fetchone()
    if exp_refs["cnt"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Chunk config is referenced by {exp_refs['cnt']} experiment(s)",
        )
    conn.execute("DELETE FROM chunks WHERE chunk_config_id = ?", (config_id,))
    conn.execute("DELETE FROM chunk_configs WHERE id = ?", (config_id,))
    conn.commit()
    return {"detail": "Chunk config deleted"}


@router.post("/projects/{project_id}/chunk-configs/{config_id}/generate")
async def generate_chunks(project_id: int, config_id: int, force: bool = False):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    config_row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    method = config_row["method"]
    params = json.loads(config_row["params_json"])
    step2_method = config_row["step2_method"]
    step2_params = (
        json.loads(config_row["step2_params_json"])
        if config_row["step2_params_json"]
        else None
    )
    filter_params = (
        json.loads(config_row["filter_params_json"])
        if config_row["filter_params_json"]
        else None
    )

    if force:
        conn.execute("DELETE FROM chunks WHERE chunk_config_id = ?", (config_id,))

    # Find document IDs that already have chunks for this config
    already_chunked = {
        row["document_id"]
        for row in conn.execute(
            "SELECT DISTINCT document_id FROM chunks WHERE chunk_config_id = ?",
            (config_id,),
        ).fetchall()
    }

    documents = conn.execute(
        "SELECT id, filename, content FROM documents WHERE project_id = ?",
        (project_id,),
    ).fetchall()

    # Remove chunks for documents that no longer exist in the project
    current_doc_ids = {doc["id"] for doc in documents}
    stale_doc_ids = already_chunked - current_doc_ids
    if stale_doc_ids:
        placeholders = ",".join("?" for _ in stale_doc_ids)
        conn.execute(
            f"DELETE FROM chunks WHERE chunk_config_id = ? AND document_id IN ({placeholders})",
            (config_id, *stale_doc_ids),
        )

    total_chunks = 0
    skipped = 0
    doc_results = []
    for doc in documents:
        if not force and doc["id"] in already_chunked:
            existing_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM chunks WHERE document_id = ? AND chunk_config_id = ?",
                (doc["id"], config_id),
            ).fetchone()["cnt"]
            total_chunks += existing_count
            skipped += 1
            doc_results.append(
                {
                    "document_id": doc["id"],
                    "filename": doc["filename"],
                    "chunk_count": existing_count,
                    "skipped": True,
                }
            )
            continue

        chunks = chunk_text_pipeline(
            doc["content"], method, params, step2_method, step2_params, filter_params
        )
        for chunk in chunks:
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_config_id, content) VALUES (?, ?, ?)",
                (doc["id"], config_id, chunk),
            )
        total_chunks += len(chunks)
        doc_results.append(
            {
                "document_id": doc["id"],
                "filename": doc["filename"],
                "chunk_count": len(chunks),
                "skipped": False,
            }
        )

    conn.commit()
    return {
        "total_chunks": total_chunks,
        "skipped_documents": skipped,
        "documents": doc_results,
    }


@router.post("/projects/{project_id}/chunk-configs/{config_id}/preview")
async def preview_chunks(project_id: int, config_id: int, document_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    config_row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")
    doc = conn.execute(
        "SELECT id, filename, content FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    method = config_row["method"]
    params = json.loads(config_row["params_json"])
    step2_method = config_row["step2_method"]
    step2_params = (
        json.loads(config_row["step2_params_json"])
        if config_row["step2_params_json"]
        else None
    )
    filter_params = (
        json.loads(config_row["filter_params_json"])
        if config_row["filter_params_json"]
        else None
    )

    chunks = chunk_text_pipeline(
        doc["content"], method, params, step2_method, step2_params, filter_params
    )
    return {
        "document_id": doc["id"],
        "filename": doc["filename"],
        "chunks": chunks,
        "chunk_count": len(chunks),
    }
