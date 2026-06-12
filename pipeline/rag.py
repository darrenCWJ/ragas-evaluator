"""RAG query engine (single-shot and multi-step).

Retrieves contexts from the vector store based on the RAG config's search type,
builds a prompt, calls the LLM, and returns the answer with retrieved contexts.
"""

import asyncio
import json
import logging

from fastapi import HTTPException

from config import CONTEXT_CHAR_BUDGET
from pipeline.bm25 import get_index_path, load_index, search_bm25
from pipeline.embedding import embed_query_dispatch
from pipeline.llm import chat_completion
from pipeline.reranker import rerank
from pipeline.vectorstore import search as vector_search

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question based only on the "
    "provided context. If the context doesn't contain enough information, say so."
)

MULTI_QUERY_SYSTEM_PROMPT = (
    "You generate alternative phrasings of a search query for a retrieval system. "
    "Rewrite the user's query from different angles (synonyms, sub-questions, "
    "more specific or more general forms) while preserving its intent. "
    "Return ONLY the rewritten queries, one per line, no numbering or commentary."
)

HYDE_SYSTEM_PROMPT = (
    "You write a short hypothetical document that would perfectly answer the "
    "user's question. Write 3-6 sentences of plausible, factual-sounding prose "
    "as if excerpted from a reference document. Return ONLY the passage."
)

# Over-fetch multiplier when MMR diversity selection is enabled
_MMR_FETCH_MULTIPLIER = 3
_MAX_FETCH_K = 50


def _cfg(config_row, key: str, default=None):
    """Read an optional field from a rag-config row (sqlite Row or dict)."""
    try:
        value = config_row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


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


def _expand_to_parents(
    contexts: list[dict], conn, seen_parents: set[str] | None = None
) -> list[dict]:
    """Small-to-big expansion: swap child-chunk hits for their parent window.

    parent_child chunk sets store parent_key/parent_content in each child's
    metadata_json (see app/routes/chunks.py). Contexts are score-ordered, so
    the first child of a parent wins and later siblings are dropped. Chunk
    sets without parent metadata pass through untouched. ``seen_parents`` lets
    multi-step retrieval dedupe parents across steps.
    """
    ids = [c["chunk_id"] for c in contexts if c.get("chunk_id") is not None]
    if not ids:
        return contexts
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, metadata_json FROM chunks WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    meta_by_id: dict[int, dict] = {}
    for r in rows:
        if not r["metadata_json"]:
            continue
        try:
            meta = json.loads(r["metadata_json"])
        except (TypeError, ValueError):
            continue
        if meta.get("parent_key") and meta.get("parent_content"):
            meta_by_id[r["id"]] = meta
    if not meta_by_id:
        return contexts

    if seen_parents is None:
        seen_parents = set()
    expanded = []
    for ctx in contexts:
        meta = meta_by_id.get(ctx.get("chunk_id"))
        if meta is None:
            expanded.append(ctx)
            continue
        parent_key = meta["parent_key"]
        if parent_key in seen_parents:
            continue
        seen_parents.add(parent_key)
        expanded.append({**ctx, "content": meta["parent_content"], "parent_key": parent_key})
    return expanded


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
    # ChromaDB queries are synchronous — keep them off the event loop.
    raw_results = await asyncio.to_thread(
        vector_search, collection_name, query_embedding, config_row["top_k"]
    )

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
            raw_dense = await asyncio.to_thread(
                vector_search, collection_name, query_embedding, top_k
            )
            for r in raw_dense:
                dense_results.append({
                    "content": r["content"],
                    "chunk_id": r["metadata"].get("chunk_id"),
                    "document_id": r["metadata"].get("document_id"),
                    "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else 0.0,
                })
        except Exception:
            logger.warning("Dense search failed in hybrid retrieval, proceeding with sparse only", exc_info=True)

    # Sparse search
    sparse_results = []
    sparse_config_id = config_row["sparse_config_id"]
    index_path = get_index_path(project_id, sparse_config_id)
    try:
        index, texts, metadatas = load_index(index_path)
        sparse_results = search_bm25(index, texts, metadatas, query, top_k)
    except FileNotFoundError:
        logger.warning("BM25 index not found at %s, sparse leg skipped", index_path)

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


async def _dispatch_retrieve(query: str, config_row, conn) -> list[dict]:
    """Route one retrieval call by search_type."""
    search_type = config_row["search_type"]
    if search_type == "dense":
        return await _retrieve_dense(query, config_row, conn)
    if search_type == "sparse":
        return await _retrieve_sparse(query, config_row, conn)
    if search_type == "hybrid":
        return await _retrieve_hybrid(query, config_row, conn)
    raise HTTPException(status_code=400, detail=f"Unknown search type: {search_type}")


async def _expand_queries(query: str, config_row) -> tuple[list[str], dict]:
    """Apply the configured query-expansion strategy.

    multi_query — LLM rewrites the query N ways; all variants (plus the
    original) are retrieved and rank-fused.
    hyde — LLM drafts a hypothetical answer passage; retrieval runs on that
    passage instead of the raw query (embedding-space match against answers).

    Returns (queries, token_usage). Expansion failures fall back to the
    original query — retrieval must never die because a rewrite call failed.
    """
    mode = _cfg(config_row, "query_expansion")
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if not mode:
        return [query], usage

    llm_params = {}
    raw_params = _cfg(config_row, "llm_params_json")
    if raw_params:
        llm_params = json.loads(raw_params) if isinstance(raw_params, str) else raw_params

    try:
        if mode == "hyde":
            result = await chat_completion(
                model=config_row["llm_model"],
                messages=[
                    {"role": "system", "content": HYDE_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                params=llm_params,
            )
            usage["prompt_tokens"] += result["usage"]["prompt_tokens"]
            usage["completion_tokens"] += result["usage"]["completion_tokens"]
            hypothetical = result["content"].strip()
            return ([hypothetical] if hypothetical else [query]), usage

        if mode == "multi_query":
            n = int(_cfg(config_row, "num_expansions", 3))
            result = await chat_completion(
                model=config_row["llm_model"],
                messages=[
                    {"role": "system", "content": MULTI_QUERY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Query: {query}\n\nGenerate {n} alternatives."},
                ],
                params=llm_params,
            )
            usage["prompt_tokens"] += result["usage"]["prompt_tokens"]
            usage["completion_tokens"] += result["usage"]["completion_tokens"]
            alternatives = [
                line.strip().lstrip("-•0123456789. ").strip()
                for line in result["content"].splitlines()
                if line.strip()
            ]
            alternatives = [a for a in alternatives if a and a.lower() != query.lower()][:n]
            return [query, *alternatives], usage
    except Exception:
        logger.warning("Query expansion (%s) failed — using the original query", mode, exc_info=True)
    return [query], usage


def _rrf_fuse(result_lists: list[list[dict]], top_k: int) -> list[dict]:
    """Reciprocal-rank-fusion across per-query result lists (multi-query)."""
    rrf_k = 60
    fused: dict = {}
    for results in result_lists:
        for rank, ctx in enumerate(results):
            key = ctx.get("chunk_id")
            if key is None:
                key = "content:" + ctx["content"][:200]
            entry = fused.setdefault(key, {"ctx": ctx, "score": 0.0})
            entry["score"] += 1.0 / (rrf_k + rank + 1)
    ranked = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:top_k]
    return [{**e["ctx"], "score": round(e["score"], 6)} for e in ranked]


def _apply_score_threshold(contexts: list[dict], threshold) -> list[dict]:
    """Drop weakly-scored hits instead of blindly keeping top_k. Unscored
    contexts pass through (their relevance is unknown, not low)."""
    if threshold is None:
        return contexts
    kept = [c for c in contexts if c.get("score") is None or c["score"] >= threshold]
    if len(kept) < len(contexts):
        logger.info(
            "Score threshold %.4f dropped %d of %d retrieved contexts",
            threshold, len(contexts) - len(kept), len(contexts),
        )
    return kept


def _mmr_select(contexts: list[dict], top_k: int, lam: float) -> list[dict]:
    """Maximal-marginal-relevance selection over an over-fetched candidate set.

    Relevance is the min-max-normalised retrieval score; redundancy is token-set
    Jaccard similarity against already-selected contexts (deterministic, no
    extra embedding calls). lam=1.0 → pure relevance, lam=0.0 → pure diversity.
    """
    if len(contexts) <= top_k:
        return contexts

    scores = [c.get("score") or 0.0 for c in contexts]
    lo, hi = min(scores), max(scores)
    if lo >= 0.0 and hi <= 1.0:
        # Already on the same [0,1] scale as Jaccard redundancy (dense/RRF).
        # Min-max here would zero the weakest hit and distort clustered scores.
        relevance = scores
    else:
        span = (hi - lo) or 1.0
        relevance = [(s - lo) / span for s in scores]
    token_sets = [set(c["content"].lower().split()) for c in contexts]

    def jaccard(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    remaining = list(range(len(contexts)))
    selected: list[int] = []
    while remaining and len(selected) < top_k:
        best_idx, best_value = remaining[0], float("-inf")
        for idx in remaining:
            redundancy = max(
                (jaccard(token_sets[idx], token_sets[s]) for s in selected), default=0.0
            )
            value = lam * relevance[idx] - (1.0 - lam) * redundancy
            if value > best_value:
                best_idx, best_value = idx, value
        selected.append(best_idx)
        remaining.remove(best_idx)
    return [contexts[i] for i in selected]


async def _kg_expand(contexts: list[dict], config_row, conn, max_extra: int) -> list[dict]:
    """Append 1-hop KG neighbours of the retrieved chunks as extra candidates.

    Best paired with a reranker (extras carry no retrieval score). No-op when
    the project has no complete chunks-KG. Never fails the query.
    """
    from pipeline import kg_retrieval

    try:
        row = kg_retrieval.fetch_kg_row(
            conn, _cfg(config_row, "project_id"), _cfg(config_row, "chunk_config_id")
        )
        if row is None:
            return contexts
        index = kg_retrieval.get_cached_index(row["id"])
        if index is None:
            # Parsing a tens-of-MB graph is CPU-bound — keep it off the event loop.
            index = await asyncio.to_thread(kg_retrieval.build_index, row["id"], row["kg_json"])
            kg_retrieval.cache_index(index)
        extras = kg_retrieval.select_neighbours(index, contexts, max_extra)
        if not extras:
            return contexts
        kg_retrieval.attach_chunk_ids(conn, extras, _cfg(config_row, "chunk_config_id"))
        logger.info("KG expansion added %d neighbour contexts", len(extras))
        return contexts + extras
    except Exception:
        logger.warning("KG expansion failed — continuing with vector hits only", exc_info=True)
        return contexts


async def _retrieve_enhanced(
    query: str, config_row, conn, seen_parent_keys: set | None = None
) -> tuple[list[dict], dict]:
    """Full retrieval pass: query expansion → search → score threshold →
    MMR/top_k cut → KG neighbour expansion → small-to-big parent swap.

    Returns (contexts, llm_token_usage_from_expansion).
    """
    top_k = config_row["top_k"]
    mmr_lambda = _cfg(config_row, "mmr_lambda")
    fetch_k = (
        min(top_k * _MMR_FETCH_MULTIPLIER, _MAX_FETCH_K) if mmr_lambda is not None else top_k
    )
    fetch_cfg = {**dict(config_row), "top_k": fetch_k}

    queries, usage = await _expand_queries(query, config_row)
    if len(queries) == 1:
        contexts = await _dispatch_retrieve(queries[0], fetch_cfg, conn)
    else:
        result_lists = [await _dispatch_retrieve(q, fetch_cfg, conn) for q in queries]
        contexts = _rrf_fuse(result_lists, fetch_k)

    contexts = _apply_score_threshold(contexts, _cfg(config_row, "score_threshold"))

    if mmr_lambda is not None:
        contexts = _mmr_select(contexts, top_k, float(mmr_lambda))
    else:
        contexts = contexts[:top_k]

    if _cfg(config_row, "kg_expansion", 0):
        contexts = await _kg_expand(contexts, config_row, conn, max_extra=top_k)

    contexts = _expand_to_parents(contexts, conn, seen_parent_keys)
    return contexts, usage


async def single_shot_query(query: str, rag_config_row, conn) -> dict:
    """Execute a single-shot RAG query: retrieve contexts, call LLM, return answer."""
    contexts, expansion_usage = await _retrieve_enhanced(query, rag_config_row, conn)

    # No contexts found
    if not contexts:
        return {
            "answer": "No relevant contexts found for your query.",
            "contexts": [],
            "model": rag_config_row["llm_model"],
            "usage": expansion_usage,
        }

    # Rerank if configured
    reranker_model = rag_config_row["reranker_model"]
    if reranker_model:
        reranker_top_k = rag_config_row["reranker_top_k"] or rag_config_row["top_k"]
        contexts = await rerank(query, contexts, reranker_model, reranker_top_k)

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
        "usage": {
            "prompt_tokens": result["usage"]["prompt_tokens"] + expansion_usage["prompt_tokens"],
            "completion_tokens": (
                result["usage"]["completion_tokens"] + expansion_usage["completion_tokens"]
            ),
        },
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
    max_steps = rag_config_row["max_steps"]

    steps = []
    all_contexts = []
    seen_chunk_ids = set()
    seen_parent_keys: set[str] = set()
    current_query = query
    total_prompt_tokens = 0
    total_completion_tokens = 0

    llm_model = rag_config_row["llm_model"]
    llm_params = {}
    if rag_config_row["llm_params_json"]:
        llm_params = json.loads(rag_config_row["llm_params_json"])

    for step_num in range(1, max_steps + 1):
        # Retrieve (expansion + threshold + MMR + KG + parent swap inside)
        raw_contexts, expansion_usage = await _retrieve_enhanced(
            current_query, rag_config_row, conn, seen_parent_keys
        )
        total_prompt_tokens += expansion_usage["prompt_tokens"]
        total_completion_tokens += expansion_usage["completion_tokens"]

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

    # Rerank all accumulated contexts if configured
    reranker_model = rag_config_row["reranker_model"]
    if reranker_model:
        reranker_top_k = rag_config_row["reranker_top_k"] or rag_config_row["top_k"]
        all_contexts = await rerank(query, all_contexts, reranker_model, reranker_top_k)

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
