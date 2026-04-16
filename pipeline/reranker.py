"""Cross-encoder reranker for improving retrieval precision.

After initial retrieval (dense, sparse, or hybrid), a cross-encoder scores
each (query, passage) pair directly, producing more accurate relevance scores
than embedding similarity alone.
"""

import asyncio
import functools
import logging

logger = logging.getLogger(__name__)

# Lazy cache for cross-encoder models
_ce_models: dict = {}


def _get_cross_encoder(model_name: str):
    """Get or load a CrossEncoder model, cached by model_name."""
    if model_name not in _ce_models:
        from sentence_transformers import CrossEncoder
        _ce_models[model_name] = CrossEncoder(model_name)
    return _ce_models[model_name]


async def rerank(
    query: str,
    contexts: list[dict],
    model_name: str,
    top_k: int | None = None,
) -> list[dict]:
    """Rerank retrieved contexts using a cross-encoder model.

    Args:
        query: The search query.
        contexts: List of dicts with at least a "content" key.
        model_name: Cross-encoder model name (e.g. "cross-encoder/ms-marco-MiniLM-L-6-v2").
        top_k: If set, return only top_k results after reranking. None keeps all.

    Returns:
        Reranked list of context dicts with updated "score" values.
    """
    if not contexts:
        return []

    model = _get_cross_encoder(model_name)
    pairs = [(query, ctx["content"]) for ctx in contexts]

    loop = asyncio.get_running_loop()
    scores = await loop.run_in_executor(
        None,
        functools.partial(model.predict, pairs),
    )

    reranked = []
    for ctx, score in zip(contexts, scores):
        reranked.append({**ctx, "score": float(score)})

    reranked.sort(key=lambda x: x["score"], reverse=True)

    if top_k is not None:
        reranked = reranked[:top_k]

    return reranked
