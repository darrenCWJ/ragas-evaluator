"""Embedding config CRUD, embed chunks, search, and hybrid search routes."""

import json
import logging

from fastapi import APIRouter, HTTPException

from app.models import (
    EmbeddingConfigCreate,
    EmbedRequest,
    HybridSearchRequest,
    SearchRequest,
)
import db.init
from pipeline.embedding import embed_query_dispatch, embed_texts_dispatch
from pipeline.vectorstore import (
    delete_collection as delete_vector_collection,
    search as vector_search,
    upsert_embeddings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["embeddings"])


def _parse_embedding_config_row(row) -> dict:
    d = dict(row)
    pj = d.pop("params_json", None)
    d["params"] = json.loads(pj) if pj else {}
    return d


@router.post("/projects/{project_id}/embedding-configs", status_code=201)
async def create_embedding_config(project_id: int, req: EmbeddingConfigCreate):
    conn = db.init.get_db()

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    cursor = conn.execute(
        "INSERT INTO embedding_configs (project_id, name, type, model_name, params_json) VALUES (?, ?, ?, ?, ?)",
        (project_id, req.name, req.type, req.model_name, json.dumps(req.params)),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM embedding_configs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _parse_embedding_config_row(row)


@router.get("/projects/{project_id}/embedding-configs")
async def list_embedding_configs(project_id: int):
    conn = db.init.get_db()

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute("SELECT * FROM embedding_configs WHERE project_id = ?", (project_id,)).fetchall()
    return [_parse_embedding_config_row(r) for r in rows]


@router.get("/projects/{project_id}/embedding-configs/{config_id}")
async def get_embedding_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")
    return _parse_embedding_config_row(row)


@router.delete("/projects/{project_id}/embedding-configs/{config_id}")
async def delete_embedding_config(project_id: int, config_id: int):
    conn = db.init.get_db()

    config_row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")
    # Referential integrity: check if any RAG configs reference this embedding config
    rag_refs = conn.execute(
        "SELECT COUNT(*) as cnt FROM rag_configs WHERE embedding_config_id = ? OR sparse_config_id = ?",
        (config_id, config_id),
    ).fetchone()
    if rag_refs["cnt"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Embedding config is referenced by {rag_refs['cnt']} RAG config(s)",
        )
    exp_refs = conn.execute(
        "SELECT COUNT(*) as cnt FROM experiments WHERE embedding_config_id = ?",
        (config_id,),
    ).fetchone()
    if exp_refs["cnt"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Embedding config is referenced by {exp_refs['cnt']} experiment(s)",
        )
    # Cascade: clean up stored data based on type
    if config_row["type"] == "bm25_sparse":
        from pipeline.bm25 import delete_index, get_index_path
        delete_index(get_index_path(project_id, config_id))
    else:
        collection_name = f"project_{project_id}_embed_{config_id}"
        delete_vector_collection(collection_name)
    conn.execute("DELETE FROM embedding_configs WHERE id = ?", (config_id,))
    conn.commit()
    return {"detail": "Embedding config deleted"}


@router.post("/projects/{project_id}/embedding-configs/{config_id}/embed")
async def embed_chunks(project_id: int, config_id: int, req: EmbedRequest):
    conn = db.init.get_db()

    # Validate project
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate embedding config belongs to project
    config_row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")

    # Validate chunk config belongs to project
    chunk_config = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if chunk_config is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    # Fetch all chunks for this chunk config
    chunks = conn.execute(
        "SELECT id, document_id, content FROM chunks WHERE chunk_config_id = ?",
        (req.chunk_config_id,),
    ).fetchall()

    # Empty state: 0 chunks -> return early
    if not chunks:
        return {"total_embedded": 0, "collection": f"project_{project_id}_embed_{config_id}"}

    embedding_type = config_row["type"]
    model_name = config_row["model_name"]
    params = json.loads(config_row["params_json"]) if config_row["params_json"] else {}

    # Build texts — optionally prepend document context for contextual embeddings
    texts = []
    if req.use_contextual_prefix:
        # Build a lookup of document_id -> context_label (falls back to filename)
        doc_ids = list({chunk["document_id"] for chunk in chunks})
        placeholders = ",".join("?" * len(doc_ids))
        docs = conn.execute(
            f"SELECT id, filename, context_label FROM documents WHERE id IN ({placeholders})",
            doc_ids,
        ).fetchall()
        doc_labels = {
            doc["id"]: doc["context_label"] or doc["filename"]
            for doc in docs
        }
        for chunk in chunks:
            label = doc_labels.get(chunk["document_id"], "Unknown")
            texts.append(f"Document: {label}\n\n{chunk['content']}")
    else:
        texts = [chunk["content"] for chunk in chunks]

    metadatas = [{"document_id": chunk["document_id"], "chunk_id": chunk["id"]} for chunk in chunks]

    if embedding_type == "bm25_sparse":
        # BM25: build index and save to disk (not ChromaDB)
        from pipeline.bm25 import build_and_save_index, get_index_path
        index_path = get_index_path(project_id, config_id)
        try:
            build_and_save_index(texts, metadatas, index_path)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"BM25 index build failed: {e}")
        return {"total_embedded": len(chunks), "index": index_path}
    else:
        # Dense embedding: compute-then-swap into ChromaDB
        try:
            embeddings = await embed_texts_dispatch(texts, embedding_type, model_name, params)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Embedding API failed: {e}")

        collection_name = f"project_{project_id}_embed_{config_id}"
        delete_vector_collection(collection_name)

        ids = [f"chunk_{chunk['id']}" for chunk in chunks]
        documents = texts

        upsert_embeddings(collection_name, ids, embeddings, documents, metadatas)

        return {"total_embedded": len(chunks), "collection": collection_name}


@router.post("/projects/{project_id}/embedding-configs/{config_id}/search")
async def search_embeddings(project_id: int, config_id: int, req: SearchRequest):
    conn = db.init.get_db()

    # Validate project
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate embedding config belongs to project
    config_row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")

    embedding_type = config_row["type"]
    model_name = config_row["model_name"]
    params = json.loads(config_row["params_json"]) if config_row["params_json"] else {}

    if embedding_type == "bm25_sparse":
        # BM25: load index and search
        from pipeline.bm25 import load_index, search_bm25, get_index_path
        index_path = get_index_path(project_id, config_id)
        try:
            index, texts, metadatas = load_index(index_path)
        except FileNotFoundError:
            return {"results": [], "query": req.query, "top_k": req.top_k}
        results = search_bm25(index, texts, metadatas, req.query, req.top_k)
        return {"results": results, "query": req.query, "top_k": req.top_k}
    else:
        # Dense: embed query and search ChromaDB
        try:
            query_embedding = await embed_query_dispatch(req.query, embedding_type, model_name, params)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Embedding API failed: {e}")

        collection_name = f"project_{project_id}_embed_{config_id}"
        results = vector_search(collection_name, query_embedding, req.top_k)

        output = []
        for r in results:
            output.append({
                "content": r["content"],
                "document_id": r["metadata"].get("document_id"),
                "chunk_id": r["metadata"].get("chunk_id"),
                "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else None,
                "distance": r["distance"],
            })

        return {"results": output, "query": req.query, "top_k": req.top_k}


@router.post("/projects/{project_id}/hybrid-search")
async def hybrid_search(project_id: int, req: HybridSearchRequest):
    conn = db.init.get_db()

    # Validate project
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate dense config
    dense_config = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (req.dense_config_id, project_id),
    ).fetchone()
    if dense_config is None:
        raise HTTPException(status_code=404, detail="Dense embedding config not found")

    # Validate sparse config
    sparse_config = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (req.sparse_config_id, project_id),
    ).fetchone()
    if sparse_config is None:
        raise HTTPException(status_code=404, detail="Sparse embedding config not found")

    # --- Dense search ---
    dense_results = []
    dense_type = dense_config["type"]
    dense_model = dense_config["model_name"]
    dense_params = json.loads(dense_config["params_json"]) if dense_config["params_json"] else {}

    try:
        query_embedding = await embed_query_dispatch(req.query, dense_type, dense_model, dense_params)
        collection_name = f"project_{project_id}_embed_{req.dense_config_id}"
        raw_dense = vector_search(collection_name, query_embedding, req.top_k)
        for r in raw_dense:
            dense_results.append({
                "content": r["content"],
                "chunk_id": r["metadata"].get("chunk_id"),
                "document_id": r["metadata"].get("document_id"),
                "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else 0.0,
            })
    except Exception:
        logger.warning("Dense search failed in hybrid endpoint, proceeding with sparse only", exc_info=True)

    # --- Sparse (BM25) search ---
    sparse_results = []
    from pipeline.bm25 import load_index, search_bm25, get_index_path
    index_path = get_index_path(project_id, req.sparse_config_id)
    try:
        index, texts, metadatas = load_index(index_path)
        sparse_results = search_bm25(index, texts, metadatas, req.query, req.top_k)
    except FileNotFoundError:
        pass

    # --- Reciprocal Rank Fusion ---
    RRF_K = 60
    chunk_scores: dict[int, dict] = {}

    for rank, r in enumerate(dense_results):
        cid = r["chunk_id"]
        if cid not in chunk_scores:
            chunk_scores[cid] = {
                "content": r["content"],
                "chunk_id": cid,
                "document_id": r["document_id"],
                "dense_score": r["score"],
                "sparse_score": None,
                "combined_score": 0.0,
            }
        chunk_scores[cid]["dense_score"] = r["score"]
        chunk_scores[cid]["combined_score"] += req.alpha * (1.0 / (RRF_K + rank + 1))

    for rank, r in enumerate(sparse_results):
        cid = r["chunk_id"]
        if cid not in chunk_scores:
            chunk_scores[cid] = {
                "content": r["content"],
                "chunk_id": cid,
                "document_id": r["document_id"],
                "dense_score": None,
                "sparse_score": r["score"],
                "combined_score": 0.0,
            }
        chunk_scores[cid]["sparse_score"] = r["score"]
        chunk_scores[cid]["combined_score"] += (1.0 - req.alpha) * (1.0 / (RRF_K + rank + 1))

    # Sort by combined score descending, take top_k
    merged = sorted(chunk_scores.values(), key=lambda x: x["combined_score"], reverse=True)[:req.top_k]

    return {"results": merged, "query": req.query, "top_k": req.top_k, "alpha": req.alpha}
