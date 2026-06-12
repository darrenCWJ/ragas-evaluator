"""KG-assisted retrieval: expand vector hits with 1-hop knowledge-graph neighbours.

The testgen knowledge graph (knowledge_graphs table) connects chunk nodes via
similarity/entity/keyphrase-overlap relationships. After normal retrieval, the
retrieved chunks' KG neighbours are appended as extra candidate contexts —
content the query embedding missed but the graph says is related. Pair with a
reranker so the extras are re-scored against the query.

The stored KG JSON is parsed directly (no ragas import — that pulls a heavy
dependency tree into the query path) into a slim index: content -> node id,
node id -> content, and a score-sorted adjacency list. Tens-of-MB graphs make
parsing expensive, so the index is cached per KG row (build it off the event
loop via asyncio.to_thread).
"""

import base64
import json
import logging
import threading
import zlib

logger = logging.getLogger(__name__)

# Mirrors evaluation/metrics/testgen.py's storage encoding — duplicated here
# (5 lines) so the query path never imports the ragas-heavy testgen module.
_KG_COMPRESS_PREFIX = "zlib64:"


def _decode_kg_json(text: str) -> str:
    if not text.startswith(_KG_COMPRESS_PREFIX):
        return text
    return zlib.decompress(base64.b64decode(text[len(_KG_COMPRESS_PREFIX):])).decode("utf-8")


def _edge_score(properties: dict) -> float:
    """Best available relationship score (same key order as the KG viewer)."""
    for key in (
        "keyphrases_overlap_score",
        "summary_similarity",
        "entities_entity_overlap",
        "overlap_score",
        "score",
    ):
        val = properties.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.5


def _node_ref_id(ref) -> str | None:
    """Relationship source/target is a node-id string or an embedded node dict."""
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        node_id = ref.get("id")
        return str(node_id) if node_id is not None else None
    return None


class KGIndex:
    """Slim lookup structure built once per stored KG row."""

    def __init__(self, kg_row_id: int):
        self.kg_row_id = kg_row_id
        self.node_id_by_content: dict[str, str] = {}
        self.content_by_node_id: dict[str, str] = {}
        # node id -> [(score, neighbour id)], sorted best-first
        self.neighbours: dict[str, list[tuple[float, str]]] = {}

    @staticmethod
    def _norm(content: str) -> str:
        return content.strip()

    def node_for_content(self, content: str) -> str | None:
        return self.node_id_by_content.get(self._norm(content))

    def neighbour_contents(self, node_id: str) -> list[str]:
        """Neighbour page contents, best edge score first."""
        out = []
        for _score, nid in self.neighbours.get(node_id, []):
            content = self.content_by_node_id.get(nid)
            if content:
                out.append(content)
        return out


def build_index(kg_row_id: int, kg_json: str) -> KGIndex:
    """Parse stored KG JSON into a KGIndex. CPU-heavy — run off the event loop."""
    data = json.loads(_decode_kg_json(kg_json))
    index = KGIndex(kg_row_id)

    for node in data.get("nodes", []):
        node_id = str(node.get("id"))
        content = (node.get("properties") or {}).get("page_content") or ""
        if not content.strip():
            continue
        index.content_by_node_id[node_id] = content
        index.node_id_by_content[KGIndex._norm(content)] = node_id

    for rel in data.get("relationships", []):
        src = _node_ref_id(rel.get("source"))
        tgt = _node_ref_id(rel.get("target"))
        if not src or not tgt or src == tgt:
            continue
        score = _edge_score(rel.get("properties") or {})
        index.neighbours.setdefault(src, []).append((score, tgt))
        index.neighbours.setdefault(tgt, []).append((score, src))

    for nid in index.neighbours:
        index.neighbours[nid].sort(key=lambda pair: pair[0], reverse=True)

    logger.info(
        "KG retrieval index built for kg row %d: %d content nodes, %d connected nodes",
        kg_row_id, len(index.content_by_node_id), len(index.neighbours),
    )
    return index


# One cached index — experiments hammer the same KG; a different KG evicts it.
_index_cache_lock = threading.Lock()
_index_cache: KGIndex | None = None


def get_cached_index(kg_row_id: int) -> KGIndex | None:
    with _index_cache_lock:
        if _index_cache is not None and _index_cache.kg_row_id == kg_row_id:
            return _index_cache
    return None


def cache_index(index: KGIndex) -> None:
    global _index_cache
    with _index_cache_lock:
        _index_cache = index


def release_index() -> int:
    """Drop the cached index (maintenance hook). Returns 1 if one was cached."""
    global _index_cache
    with _index_cache_lock:
        had = 1 if _index_cache is not None else 0
        _index_cache = None
    return had


def fetch_kg_row(conn, project_id: int, chunk_config_id: int | None):
    """Most recent complete chunks-KG for the project, preferring an exact
    chunk-config match (graph node contents must match retrieved chunk text)."""
    if project_id is None:
        return None
    if chunk_config_id is not None:
        row = conn.execute(
            "SELECT id, kg_json FROM knowledge_graphs"
            " WHERE project_id = ? AND kg_source = 'chunks' AND is_complete = 1"
            " AND chunk_config_id = ? ORDER BY created_at DESC LIMIT 1",
            (project_id, chunk_config_id),
        ).fetchone()
        if row is not None:
            return row
    return conn.execute(
        "SELECT id, kg_json FROM knowledge_graphs"
        " WHERE project_id = ? AND kg_source = 'chunks' AND is_complete = 1"
        " ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def select_neighbours(
    index: KGIndex, contexts: list[dict], max_extra: int
) -> list[dict]:
    """1-hop neighbour contexts for the given hits, best-first, deduplicated."""
    existing = {KGIndex._norm(c.get("content", "")) for c in contexts}
    extras: list[dict] = []
    for ctx in contexts:
        if len(extras) >= max_extra:
            break
        node_id = index.node_for_content(ctx.get("content", ""))
        if node_id is None:
            continue
        for content in index.neighbour_contents(node_id):
            if len(extras) >= max_extra:
                break
            norm = KGIndex._norm(content)
            if norm in existing:
                continue
            existing.add(norm)
            extras.append(
                {
                    "content": content,
                    "score": None,
                    "chunk_id": None,
                    "document_id": None,
                    "kg_expanded": True,
                }
            )
    return extras


def attach_chunk_ids(conn, extras: list[dict], chunk_config_id: int | None) -> None:
    """Map neighbour contents back to chunk rows for provenance (best effort)."""
    if not extras or chunk_config_id is None:
        return
    contents = [e["content"] for e in extras]
    placeholders = ",".join("?" for _ in contents)
    rows = conn.execute(
        f"SELECT id, document_id, content FROM chunks"
        f" WHERE chunk_config_id = ? AND content IN ({placeholders})",
        (chunk_config_id, *contents),
    ).fetchall()
    by_content = {r["content"]: r for r in rows}
    for extra in extras:
        row = by_content.get(extra["content"])
        if row is not None:
            extra["chunk_id"] = row["id"]
            extra["document_id"] = row["document_id"]
