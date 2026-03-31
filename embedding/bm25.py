"""BM25 sparse ranking for keyword-based document retrieval.

Stores indices as JSON (not pickle — audit fix for CWE-502).
Uses atomic file writes (temp + rename) to prevent corruption from concurrent requests.
"""

import json
import os
import tempfile
from pathlib import Path

from rank_bm25 import BM25Okapi


BM25_DATA_DIR = "data/bm25"


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokenization."""
    return text.lower().split()


def get_index_path(project_id: int, config_id: int) -> str:
    """Return the standard index file path for a project/config pair."""
    return f"{BM25_DATA_DIR}/project_{project_id}_embed_{config_id}.json"


def build_bm25_index(texts: list[str]) -> tuple[BM25Okapi, list[list[str]]]:
    """Tokenize texts and build a BM25Okapi index.

    Returns (index, tokenized_corpus) so corpus can be persisted.
    """
    tokenized_corpus = [_tokenize(text) for text in texts]
    index = BM25Okapi(tokenized_corpus)
    return index, tokenized_corpus


def save_index(
    tokenized_corpus: list[list[str]],
    texts: list[str],
    metadatas: list[dict],
    path: str,
) -> None:
    """Serialize BM25 index data as JSON with atomic write.

    Writes to a temp file then renames for atomic swap (audit fix).
    """
    Path(BM25_DATA_DIR).mkdir(parents=True, exist_ok=True)

    data = {
        "tokenized_corpus": tokenized_corpus,
        "texts": texts,
        "metadatas": metadatas,
    }

    # Atomic write: temp file + rename
    dir_path = os.path.dirname(path) or BM25_DATA_DIR
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.rename(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_index(path: str) -> tuple[BM25Okapi | None, list[str], list[dict]]:
    """Load a BM25 index from JSON and reconstruct BM25Okapi.

    Returns (index, texts, metadatas). index is None if corpus was empty.
    Raises FileNotFoundError if index doesn't exist.
    """
    with open(path) as f:
        data = json.load(f)

    tokenized_corpus = data["tokenized_corpus"]
    texts = data["texts"]
    metadatas = data["metadatas"]

    if not tokenized_corpus:
        return None, texts, metadatas

    index = BM25Okapi(tokenized_corpus)
    return index, texts, metadatas


def search_bm25(
    index: BM25Okapi | None,
    texts: list[str],
    metadatas: list[dict],
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """Search a BM25 index and return ranked results.

    Returns list of dicts with: content, score, chunk_id, document_id.
    Returns empty list if index is None (empty corpus).
    """
    if index is None:
        return []
    tokenized_query = _tokenize(query)
    scores = index.get_scores(tokenized_query)

    # Get top-k indices sorted by score descending
    scored_indices = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True,
    )[:top_k]

    results = []
    for idx in scored_indices:
        if scores[idx] <= 0:
            continue
        meta = metadatas[idx] if idx < len(metadatas) else {}
        results.append({
            "content": texts[idx],
            "score": float(scores[idx]),
            "chunk_id": meta.get("chunk_id"),
            "document_id": meta.get("document_id"),
        })

    return results


def build_and_save_index(
    texts: list[str],
    metadatas: list[dict],
    path: str,
) -> None:
    """Build a BM25 index and save atomically. Compute-then-swap pattern."""
    if not texts:
        # Empty corpus: save empty index
        save_index([], [], [], path)
        return
    index, tokenized_corpus = build_bm25_index(texts)
    save_index(tokenized_corpus, texts, metadatas, path)


def delete_index(path: str) -> None:
    """Delete a BM25 index file. No-op if file doesn't exist."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
