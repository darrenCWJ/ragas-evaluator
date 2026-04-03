"""RAG query engine (single-shot and multi-step).

Retrieves contexts from the vector store based on the RAG config's search type,
builds a prompt, calls the LLM, and returns the answer with retrieved contexts.
"""

import json
import logging

from fastapi import HTTPException

from embedding.engine import embed_query_dispatch
from llm.connector import chat_completion
from embedding.vectorstore import search as vector_search
from embedding.bm25 import load_index, search_bm25, get_index_path

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question based only on the "
    "provided context. If the context doesn't contain enough information, say so."
)

CONTEXT_CHAR_BUDGET = 100_000


def _build_context_text(contexts: list[dict]) -> str:
    """Format retrieved contexts into a numbered list for the LLM prompt."""
    parts = []
    for i, ctx in enumerate(contexts, 1):
        parts.append(f"[{i}] {ctx['content']}")
    return "\n\n".join(parts)


def _truncate_contexts(contexts: list[dict], system_prompt: str, query: str) -> list[dict]:
    """Drop lowest-scored contexts if total prompt size exceeds budget."""
    base_size = len(system_prompt) + len(query) + 200  # overhead for formatting
    total = base_size + sum(len(c["content"]) for c in contexts)
    if total <= CONTEXT_CHAR_BUDGET:
        return contexts

    # Contexts are already sorted by score descending; drop from the end
    truncated = list(contexts)
    while truncated and base_size + sum(len(c["content"]) for c in truncated) > CONTEXT_CHAR_BUDGET:
        truncated.pop()

    logger.warning(
        "Context truncation: dropped %d of %d contexts to fit within %d char budget",
        len(contexts) - len(truncated), len(contexts), CONTEXT_CHAR_BUDGET,
    )
    return truncated


async def _retrieve_dense(query: str, config_row, conn) -> list[dict]:
    """Retrieve contexts using dense vector search."""
    embedding_config = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ?",
        (config_row["embedding_config_id"],),
    ).fetchone()

    embedding_type = embedding_config["type"]
    model_name = embedding_config["model_name"]
    params = json.loads(embedding_config["params_json"]) if embedding_config["params_json"] else {}

    query_embedding = await embed_query_dispatch(query, embedding_type, model_name, params)
    project_id = config_row["project_id"]
    collection_name = f"project_{project_id}_embed_{config_row['embedding_config_id']}"
    raw_results = vector_search(collection_name, query_embedding, config_row["top_k"])

    return [
        {
            "content": r["content"],
            "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else None,
            "chunk_id": r["metadata"].get("chunk_id"),
            "document_id": r["metadata"].get("document_id"),
        }
        for r in raw_results
    ]


async def _retrieve_sparse(query: str, config_row, conn) -> list[dict]:
    """Retrieve contexts using BM25 sparse search."""
    project_id = config_row["project_id"]
    # For sparse search_type, use the embedding_config_id (which should be a BM25 config)
    embed_config_id = config_row["embedding_config_id"]
    index_path = get_index_path(project_id, embed_config_id)
    try:
        index, texts, metadatas = load_index(index_path)
    except FileNotFoundError:
        return []
    return search_bm25(index, texts, metadatas, query, config_row["top_k"])


async def _retrieve_hybrid(query: str, config_row, conn) -> list[dict]:
    """Retrieve contexts using hybrid (dense + sparse) search with RRF."""
    project_id = config_row["project_id"]
    top_k = config_row["top_k"]
    alpha = config_row["alpha"]

    # Dense search
    dense_results = []
    embedding_config = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ?",
        (config_row["embedding_config_id"],),
    ).fetchone()
    if embedding_config:
        embedding_type = embedding_config["type"]
        model_name = embedding_config["model_name"]
        params = json.loads(embedding_config["params_json"]) if embedding_config["params_json"] else {}
        try:
            query_embedding = await embed_query_dispatch(query, embedding_type, model_name, params)
            collection_name = f"project_{project_id}_embed_{config_row['embedding_config_id']}"
            raw_dense = vector_search(collection_name, query_embedding, top_k)
            for r in raw_dense:
                dense_results.append({
                    "content": r["content"],
                    "chunk_id": r["metadata"].get("chunk_id"),
                    "document_id": r["metadata"].get("document_id"),
                    "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else 0.0,
                })
        except Exception:
            pass

    # Sparse search
    sparse_results = []
    sparse_config_id = config_row["sparse_config_id"]
    index_path = get_index_path(project_id, sparse_config_id)
    try:
        index, texts, metadatas = load_index(index_path)
        sparse_results = search_bm25(index, texts, metadatas, query, top_k)
    except FileNotFoundError:
        pass

    # Reciprocal Rank Fusion
    RRF_K = 60
    chunk_scores: dict[int, dict] = {}

    for rank, r in enumerate(dense_results):
        cid = r["chunk_id"]
        if cid not in chunk_scores:
            chunk_scores[cid] = {
                "content": r["content"],
                "chunk_id": cid,
                "document_id": r["document_id"],
                "score": 0.0,
            }
        chunk_scores[cid]["score"] += alpha * (1.0 / (RRF_K + rank + 1))

    for rank, r in enumerate(sparse_results):
        cid = r["chunk_id"]
        if cid not in chunk_scores:
            chunk_scores[cid] = {
                "content": r["content"],
                "chunk_id": cid,
                "document_id": r["document_id"],
                "score": 0.0,
            }
        chunk_scores[cid]["score"] += (1.0 - alpha) * (1.0 / (RRF_K + rank + 1))

    merged = sorted(chunk_scores.values(), key=lambda x: x["score"], reverse=True)[:top_k]
    return merged


async def single_shot_query(query: str, rag_config_row, conn) -> dict:
    """Execute a single-shot RAG query: retrieve contexts, call LLM, return answer."""
    search_type = rag_config_row["search_type"]

    # Retrieve contexts based on search type
    if search_type == "dense":
        contexts = await _retrieve_dense(query, rag_config_row, conn)
    elif search_type == "sparse":
        contexts = await _retrieve_sparse(query, rag_config_row, conn)
    elif search_type == "hybrid":
        contexts = await _retrieve_hybrid(query, rag_config_row, conn)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown search type: {search_type}")

    # No contexts found
    if not contexts:
        return {
            "answer": "No relevant contexts found for your query.",
            "contexts": [],
            "model": rag_config_row["llm_model"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    # Build prompt
    system_prompt = rag_config_row["system_prompt"] or DEFAULT_SYSTEM_PROMPT

    # Truncate contexts if needed
    contexts = _truncate_contexts(contexts, system_prompt, query)

    context_text = _build_context_text(contexts)
    user_message = f"Context:\n{context_text}\n\nQuestion: {query}"

    # Parse LLM params
    llm_params = {}
    if rag_config_row["llm_params_json"]:
        llm_params = json.loads(rag_config_row["llm_params_json"])

    # Call LLM via connector
    result = await chat_completion(
        model=rag_config_row["llm_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        params=llm_params,
    )

    return {
        "answer": result["content"],
        "contexts": contexts,
        "model": rag_config_row["llm_model"],
        "usage": result["usage"],
    }


GAP_ANALYSIS_SYSTEM_PROMPT = (
    "You are analyzing whether the provided context is sufficient to answer the "
    "user's question. If gaps exist, generate a refined search query to find the "
    "missing information. If sufficient, respond with sufficient=true."
)

GAP_ANALYSIS_USER_TEMPLATE = (
    "Question: {question}\n\n"
    "Context so far:\n{all_context}\n\n"
    "New context from this step:\n{new_context}\n\n"
    "Analyze: Is the context sufficient to answer the question? If not, what "
    "specific information is missing? Respond in this exact JSON format:\n"
    '{{"sufficient": true/false, "reasoning": "...", "refined_query": "..." or null}}'
)


async def multi_step_query(query: str, rag_config_row, conn) -> dict:
    """Execute a multi-step RAG query: iteratively retrieve, reason about gaps, and synthesize."""
    search_type = rag_config_row["search_type"]
    max_steps = rag_config_row["max_steps"]

    steps = []
    all_contexts = []
    seen_chunk_ids = set()
    current_query = query
    total_prompt_tokens = 0
    total_completion_tokens = 0

    llm_model = rag_config_row["llm_model"]
    llm_params = {}
    if rag_config_row["llm_params_json"]:
        llm_params = json.loads(rag_config_row["llm_params_json"])

    for step_num in range(1, max_steps + 1):
        # Retrieve contexts based on search type
        if search_type == "dense":
            raw_contexts = await _retrieve_dense(current_query, rag_config_row, conn)
        elif search_type == "sparse":
            raw_contexts = await _retrieve_sparse(current_query, rag_config_row, conn)
        elif search_type == "hybrid":
            raw_contexts = await _retrieve_hybrid(current_query, rag_config_row, conn)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown search type: {search_type}")

        # Deduplicate: only keep contexts with chunk_ids not yet seen
        new_contexts = []
        for ctx in raw_contexts:
            cid = ctx.get("chunk_id")
            if cid is not None and cid in seen_chunk_ids:
                continue
            if cid is not None:
                seen_chunk_ids.add(cid)
            new_contexts.append(ctx)

        # No new contexts found — break early
        if not new_contexts:
            steps.append({
                "step": step_num,
                "sub_query": current_query,
                "new_contexts_count": 0,
                "reasoning": "No new contexts found",
                "sufficient": True,
            })
            break

        all_contexts.extend(new_contexts)

        # Gap analysis LLM call
        all_context_text = _build_context_text(all_contexts)
        new_context_text = _build_context_text(new_contexts)
        gap_user_msg = GAP_ANALYSIS_USER_TEMPLATE.format(
            question=query,
            all_context=all_context_text,
            new_context=new_context_text,
        )

        sufficient = True
        reasoning = ""
        refined_query = None

        gap_result = await chat_completion(
            model=llm_model,
            messages=[
                {"role": "system", "content": GAP_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": gap_user_msg},
            ],
            params=llm_params,
        )
        total_prompt_tokens += gap_result["usage"]["prompt_tokens"]
        total_completion_tokens += gap_result["usage"]["completion_tokens"]

        gap_text = gap_result["content"].strip()
        try:
            gap_parsed = json.loads(gap_text)
            sufficient = gap_parsed.get("sufficient", True)
            reasoning = gap_parsed.get("reasoning", "")
            refined_query = gap_parsed.get("refined_query")
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Gap analysis JSON parse failed for step %d, treating as sufficient", step_num)
            sufficient = True
            reasoning = "Gap analysis response could not be parsed"

        steps.append({
            "step": step_num,
            "sub_query": current_query,
            "new_contexts_count": len(new_contexts),
            "reasoning": reasoning,
            "sufficient": sufficient,
        })

        if sufficient:
            break

        if refined_query:
            current_query = refined_query

    # No contexts gathered at all
    if not all_contexts:
        return {
            "answer": "No relevant contexts found for your query.",
            "contexts": [],
            "model": llm_model,
            "usage": {"prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens},
            "steps": steps,
            "response_mode": "multi_step",
        }

    # Synthesize final answer using all accumulated contexts
    system_prompt = rag_config_row["system_prompt"] or DEFAULT_SYSTEM_PROMPT
    all_contexts = _truncate_contexts(all_contexts, system_prompt, query)
    context_text = _build_context_text(all_contexts)
    user_message = f"Context:\n{context_text}\n\nQuestion: {query}"

    synth_result = await chat_completion(
        model=llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        params=llm_params,
    )
    total_prompt_tokens += synth_result["usage"]["prompt_tokens"]
    total_completion_tokens += synth_result["usage"]["completion_tokens"]

    return {
        "answer": synth_result["content"],
        "contexts": all_contexts,
        "model": llm_model,
        "usage": {"prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens},
        "steps": steps,
        "response_mode": "multi_step",
    }
