"""Chunk-source resolution for test set generation.

Shared by the main app route (``app/routes/testsets.py``) and the worker's
``/run-testgen`` endpoint so both resolve generation sources identically.
"""

from fastapi import HTTPException

from config import MAX_CHUNKS_FOR_GENERATION

# Categories that only need the Graph RAG document KG (no chunk config).
GRAPH_RAG_ONLY_CATS = {"bridge", "comparative", "community"}


def load_generation_chunks(conn, project_id: int, req) -> list[str]:
    """Resolve the chunk texts used as the generation source for a test set.

    Three sourcing options, mirroring the original route logic:

    A. ``use_kg_as_source`` — node page_content straight from the stored KG.
    B. Graph RAG (Documents) only — no chunks needed, returns ``[]``.
    C. Normal — chunks from ``req.chunk_config_id``.

    Raises HTTPException on invalid configuration.
    """
    if req.use_kg_as_source:
        import json as _json

        from evaluation.metrics.testgen import load_full_kg_json

        kg_json = load_full_kg_json(project_id, "chunks")
        if kg_json is None:
            raise HTTPException(
                status_code=422,
                detail="No complete knowledge graph found for this project. Build a knowledge graph first.",
            )
        nodes = _json.loads(kg_json).get("nodes", [])
        chunks = [
            n.get("properties", {}).get("page_content", "")
            for n in nodes
            if n.get("properties", {}).get("page_content", "").strip()
        ]
        if not chunks:
            raise HTTPException(
                status_code=422,
                detail="Knowledge graph exists but contains no node content.",
            )
        return chunks

    if (
        req.graph_rag_kg_source == "documents"
        and req.question_categories
        and set(req.question_categories.keys()) <= GRAPH_RAG_ONLY_CATS
    ):
        return []

    if req.chunk_config_id is None:
        raise HTTPException(
            status_code=422,
            detail="chunk_config_id required unless using only Graph RAG (Documents) categories",
        )

    cc = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if cc is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    chunk_rows = conn.execute(
        "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
        (req.chunk_config_id,),
    ).fetchall()
    if not chunk_rows:
        raise HTTPException(
            status_code=422,
            detail="No chunks found for this config. Generate chunks first.",
        )

    if MAX_CHUNKS_FOR_GENERATION > 0 and len(chunk_rows) > MAX_CHUNKS_FOR_GENERATION:
        raise HTTPException(
            status_code=422,
            detail=f"Too many chunks ({len(chunk_rows)}). Maximum {MAX_CHUNKS_FOR_GENERATION} supported for test generation.",
        )

    return [r["content"] for r in chunk_rows]
