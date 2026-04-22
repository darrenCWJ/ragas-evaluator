"""Embedding engine for generating vector representations of text chunks.

Supports multiple embedding strategies with type-based dispatch:
- dense_openai: OpenAI API embeddings
- dense_sentence_transformers: Local sentence-transformers models
"""

import asyncio
import functools

from openai import AsyncOpenAI

from config import EMBEDDING_BATCH_SIZE

BATCH_SIZE = EMBEDDING_BATCH_SIZE

# Module-level OpenAI client for embedding (connection reuse)
_openai_embed_client: AsyncOpenAI | None = None


def _get_openai_embed_client() -> AsyncOpenAI:
    global _openai_embed_client
    if _openai_embed_client is None:
        _openai_embed_client = AsyncOpenAI(
            max_retries=1,
            timeout=60.0,
        )
    return _openai_embed_client


async def close_openai_embed_client() -> None:
    """Close module-level embedding OpenAI client. Call during app shutdown."""
    global _openai_embed_client
    if _openai_embed_client is not None:
        await _openai_embed_client.close()
        _openai_embed_client = None


# Lazy cache for sentence-transformers models (audit fix — avoids re-loading per request)
_st_models: dict = {}


def _get_st_model(model_name: str):
    """Get or load a SentenceTransformer model, cached by model_name."""
    if model_name not in _st_models:
        from sentence_transformers import SentenceTransformer
        _st_models[model_name] = SentenceTransformer(model_name)
    return _st_models[model_name]


async def _embed_openai(texts: list[str], model_name: str, params: dict) -> list[list[float]]:
    """Embed texts using OpenAI API. Batches in groups of BATCH_SIZE."""
    if not texts:
        return []

    client = _get_openai_embed_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = await client.embeddings.create(
            input=batch,
            model=model_name,
            **params,
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


async def _embed_sentence_transformers(texts: list[str], model_name: str, params: dict) -> list[list[float]]:
    """Embed texts using a local sentence-transformers model.

    Runs model.encode() in a thread pool since sentence-transformers is synchronous.
    """
    if not texts:
        return []

    model = _get_st_model(model_name)
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(
        None,
        functools.partial(model.encode, texts, **params),
    )
    return [emb.tolist() for emb in embeddings]


_DISPATCH = {
    "dense_openai": _embed_openai,
    "openai": _embed_openai,
    "dense_sentence_transformers": _embed_sentence_transformers,
    "sentence_transformers": _embed_sentence_transformers,
}


async def embed_texts_dispatch(
    texts: list[str], embedding_type: str, model_name: str, params: dict
) -> list[list[float]]:
    """Dispatch embedding to the correct engine based on type."""
    handler = _DISPATCH.get(embedding_type)
    if handler is None:
        raise ValueError(f"Unsupported embedding type: {embedding_type}")
    return await handler(texts, model_name, params)


async def embed_query_dispatch(
    query: str, embedding_type: str, model_name: str, params: dict
) -> list[float]:
    """Embed a single query string via dispatch."""
    results = await embed_texts_dispatch([query], embedding_type, model_name, params)
    return results[0]
