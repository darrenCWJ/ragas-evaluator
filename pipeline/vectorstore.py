"""ChromaDB vector store for persistent embedding storage and similarity search."""

import chromadb
from pathlib import Path

from config import CHROMADB_PATH

PERSIST_DIRECTORY = str(CHROMADB_PATH)

_client: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        Path(PERSIST_DIRECTORY).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)
    return _client


def get_or_create_collection(collection_name: str) -> chromadb.Collection:
    """Get an existing collection or create a new one."""
    client = _get_client()
    return client.get_or_create_collection(name=collection_name)


def upsert_embeddings(
    collection_name: str,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict],
) -> None:
    """Upsert vectors with metadata into a ChromaDB collection."""
    collection = get_or_create_collection(collection_name)
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )


def search(
    collection_name: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Query a ChromaDB collection by embedding vector.

    Returns list of dicts with keys: content, metadata, distance.
    Returns empty list if collection doesn't exist or has no data.
    """
    client = _get_client()
    try:
        collection = client.get_collection(name=collection_name)
    except Exception as e:
        if "not found" in str(e).lower() or "does not exist" in str(e).lower():
            return []
        raise

    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
    )

    output = []
    for i in range(len(results["ids"][0])):
        output.append({
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "distance": results["distances"][0][i] if results["distances"] else None,
        })

    return output


def delete_collection(collection_name: str) -> None:
    """Delete an entire collection. No-op if collection doesn't exist."""
    client = _get_client()
    try:
        client.delete_collection(name=collection_name)
    except Exception as e:
        # chromadb may raise NotFoundError or ValueError depending on version
        if "not found" in str(e).lower() or "does not exist" in str(e).lower():
            pass
        else:
            raise
