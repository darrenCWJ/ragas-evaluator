"""Test question generation using Ragas testset generators.

Supports:
- Auto-generating personas from documents
- Single-hop questions (fact lookup from one chunk)
- Multi-hop questions (reasoning across multiple chunks)
- Pre-chunked data input
- Custom persona definitions
- Custom query distribution (single-hop / multi-hop mix)
- Post-generation deduplication (fuzzy matching)
- Parallel batch generation for large test sets
"""

import hashlib
import json as _json
import logging
import math
import os
import random
import signal
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from openai import AsyncOpenAI, OpenAI
from ragas.llms import llm_factory
from ragas.embeddings import embedding_factory
from ragas.testset import TestsetGenerator
from ragas.testset.persona import Persona, generate_personas_from_kg
from ragas.testset.graph import KnowledgeGraph, Node, NodeType
from ragas.testset.transforms import (
    apply_transforms,
    CosineSimilarityBuilder,
    EmbeddingExtractor,
    HeadlinesExtractor,
    HeadlineSplitter,
    KeyphrasesExtractor,
    OverlapScoreBuilder,
    SummaryExtractor,
)
from ragas.testset.transforms.default import CustomNodeFilter, NERExtractor, ThemesExtractor
from ragas.testset.synthesizers.single_hop.specific import SingleHopSpecificQuerySynthesizer
from ragas.testset.synthesizers.multi_hop import (
    MultiHopAbstractQuerySynthesizer,
    MultiHopSpecificQuerySynthesizer,
)

from config import (
    DEFAULT_EVAL_EMBEDDING,
    DEFAULT_EVAL_MAX_TOKENS,
    DEFAULT_EVAL_MODEL,
    KG_BATCH_SIZE,
    PERSONA_MAX_CHARS_PER_BATCH,
    TESTGEN_PERSONA_TEMPERATURE,
    TESTGEN_QUESTION_TEMPERATURE,
    TESTGEN_TOPIC_TEMPERATURE,
)
from db.init import get_db, NOW_SQL


logger = logging.getLogger(__name__)

# Suppress noisy ragas warnings about duplicate node properties.
logging.getLogger("ragas.testset.graph").setLevel(logging.ERROR)
logging.getLogger("ragas.testset.transforms").setLevel(logging.ERROR)

# Event checked by workers so Ctrl+C stops generation promptly.
_shutdown_event = threading.Event()


def _register_shutdown_handler() -> None:
    """Set _shutdown_event on SIGINT so background workers can exit early.

    Only works when called from the main thread; silently skipped otherwise
    (e.g. when running inside ``run_in_executor``).
    """
    if threading.current_thread() is not threading.main_thread():
        return

    def _handler(signum, frame):
        _shutdown_event.set()
        logger.info("Shutdown requested — stopping test generation workers...")

    signal.signal(signal.SIGINT, _handler)


# ---------------------------------------------------------------------------
# Progress tracking — in-memory, keyed by (project_id, kg_source).
# Use kg_source="testset" for test-set generation progress.
# ---------------------------------------------------------------------------

_progress_lock = threading.Lock()
_progress: dict[tuple[int, str], dict] = {}


def set_progress(project_id: int, data: dict, kg_source: str = "chunks") -> None:
    with _progress_lock:
        _progress[(project_id, kg_source)] = data
    if os.environ.get("KG_PROGRESS_PIPE"):
        print(_json.dumps({"_progress": True, "project_id": project_id, "kg_source": kg_source, **data}), flush=True)


def update_progress(project_id: int, kg_source: str = "chunks", **fields) -> None:
    with _progress_lock:
        key = (project_id, kg_source)
        if key in _progress:
            _progress[key].update(fields)
            snapshot = dict(_progress[key])
        else:
            snapshot = fields
    if os.environ.get("KG_PROGRESS_PIPE"):
        print(_json.dumps({"_progress": True, "project_id": project_id, "kg_source": kg_source, **snapshot}), flush=True)


def get_progress(project_id: int, kg_source: str = "chunks") -> dict | None:
    with _progress_lock:
        entry = _progress.get((project_id, kg_source))
        return entry.copy() if entry is not None else None


def clear_progress(project_id: int, kg_source: str = "chunks") -> None:
    with _progress_lock:
        _progress.pop((project_id, kg_source), None)


# ---------------------------------------------------------------------------
# Per-project cancel flags — set by the cancel endpoint, checked in workers
# ---------------------------------------------------------------------------

_cancel_lock = threading.Lock()
_cancel_flags: dict[int, threading.Event] = {}  # project_id -> Event


def register_cancel_flag(project_id: int) -> threading.Event:
    event = threading.Event()
    with _cancel_lock:
        _cancel_flags[project_id] = event
    return event


def clear_cancel_flag(project_id: int) -> None:
    with _cancel_lock:
        _cancel_flags.pop(project_id, None)


def cancel_generation(project_id: int) -> bool:
    """Set the cancel flag for the given project. Returns True if a flag was found."""
    with _cancel_lock:
        flag = _cancel_flags.get(project_id)
    if flag is not None:
        flag.set()
        return True
    return False


def is_cancelled(project_id: int | None) -> bool:
    if project_id is None:
        return False
    with _cancel_lock:
        flag = _cancel_flags.get(project_id)
    return flag is not None and flag.is_set()


# ---------------------------------------------------------------------------
# KG helpers — load full KG without hash check, and sample nodes from JSON
# ---------------------------------------------------------------------------

def load_full_kg_json(project_id: int, kg_source: str = "chunks") -> str | None:
    """Return raw JSON of the most recent *complete* KG for a project.

    Unlike ``load_cached_kg``, this ignores the chunks hash so it works
    even when the caller doesn't have the original chunk list.  Returns
    ``None`` if no complete KG exists.
    """
    db = get_db()
    row = db.execute(
        "SELECT kg_json FROM knowledge_graphs "
        "WHERE project_id = ? AND kg_source = ? AND is_complete = TRUE "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id, kg_source),
    ).fetchone()
    return row["kg_json"] if row is not None else None


def _load_kg_from_json_str(kg_json: str) -> KnowledgeGraph:
    """Load a KnowledgeGraph from a raw JSON string (via a temp file)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(kg_json)
        tmp_path = f.name
    try:
        return _load_kg_safe(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Fast-mode combined extractor — replaces 5 separate LLM steps with 1
# ---------------------------------------------------------------------------

class CombinedNodeExtractor:
    """One LLM call per node extracts keyphrases, summary, themes, entities,
    and a quality-filter flag.  Designed as a drop-in Ragas transform step.

    Replaces: KeyphrasesExtractor + SummaryExtractor + CustomNodeFilter +
              ThemesExtractor + NERExtractor  (5 LLM rounds → 1).
    """

    def __init__(
        self,
        model: str = "",
        max_keyphrases: int = 10,
        max_themes: int = 3,
        max_entities: int = 10,
    ) -> None:
        self.model = model
        self.max_keyphrases = max_keyphrases
        self.max_themes = max_themes
        self.max_entities = max_entities

    def generate_execution_plan(self, kg: "KnowledgeGraph") -> list:  # type: ignore[return]
        from ragas.testset.graph import KnowledgeGraph as _KG  # noqa: F401
        from pipeline.llm import chat_completion

        async def _process(node) -> None:
            text = node.properties.get("page_content", "")
            if not text or not text.strip():
                node.properties.update(
                    keyphrases=[], summary="", themes=[], entities=[], _fast_keep=False
                )
                return

            prompt = (
                "Analyze the following text. Respond with ONLY a JSON object.\n\n"
                f"TEXT:\n{text[:8000]}\n\n"
                "Return a JSON object with these fields:\n"
                f"- keyphrases: list of up to {self.max_keyphrases} key phrases\n"
                "- summary: 1-2 sentence summary\n"
                f"- themes: list of up to {self.max_themes} high-level themes\n"
                f"- entities: list of up to {self.max_entities} named entities "
                "(people, organisations, places, concepts)\n"
                "- keep: true if the text is informative enough for a knowledge graph, "
                "false if it is empty, trivial, or purely navigational\n\n"
                '{"keyphrases": [...], "summary": "...", "themes": [...], '
                '"entities": [...], "keep": true}'
            )
            try:
                result = await chat_completion(
                    self.model,
                    [{"role": "user", "content": prompt}],
                    {"temperature": 0.0, "max_tokens": 600},
                )
                data = _extract_json(result["content"])
                node.properties.update(
                    keyphrases=[str(k) for k in data.get("keyphrases", [])][: self.max_keyphrases],
                    summary=str(data.get("summary", "")),
                    themes=[str(t) for t in data.get("themes", [])][: self.max_themes],
                    entities=[str(e) for e in data.get("entities", [])][: self.max_entities],
                    _fast_keep=bool(data.get("keep", True)),
                )
            except Exception as exc:
                logger.warning("CombinedNodeExtractor failed for node: %s", exc)
                node.properties.setdefault("keyphrases", [])
                node.properties.setdefault("summary", "")
                node.properties.setdefault("themes", [])
                node.properties.setdefault("entities", [])
                node.properties.setdefault("_fast_keep", True)

        return [_process(node) for node in kg.nodes]


def sample_kg_from_json(kg_json: str, n: int) -> tuple[KnowledgeGraph, list[str]]:
    """Sample *n* nodes from a serialised KG, filter dangling edges, and return
    the resulting ``KnowledgeGraph`` together with the corresponding chunk texts.

    If *n* ≥ total nodes the full KG is returned unchanged.
    """
    import json as _json

    data = _json.loads(kg_json)
    nodes = data.get("nodes", [])

    if n >= len(nodes):
        sampled_nodes = nodes
    else:
        sampled_nodes = random.sample(nodes, n)

    sampled_ids = {node["id"] for node in sampled_nodes}
    filtered_rels = [
        r for r in data.get("relationships", [])
        if r.get("source") in sampled_ids and r.get("target") in sampled_ids
    ]

    new_json = _json.dumps({**data, "nodes": sampled_nodes, "relationships": filtered_rels})
    kg = _load_kg_from_json_str(new_json)
    chunk_texts = [
        node.get("properties", {}).get("page_content", "") for node in sampled_nodes
    ]
    return kg, chunk_texts




def increment_questions(project_id: int, count: int = 1) -> None:
    with _progress_lock:
        key = (project_id, "testset")
        if key in _progress:
            _progress[key]["questions_generated"] = (
                _progress[key].get("questions_generated", 0) + count
            )


# Over-generate per worker, then deduplicate and trim to requested size.
OVERGENERATE_FACTOR = 1.5
# Two questions are considered duplicates if similarity exceeds this threshold.
SIMILARITY_THRESHOLD = 0.75
# Minimum chunks per worker — below this, fewer workers are used.
MIN_CHUNKS_PER_WORKER = 5


SYNTHESIZER_MAP = {
    "single_hop_specific": SingleHopSpecificQuerySynthesizer,
    "multi_hop_abstract": MultiHopAbstractQuerySynthesizer,
    "multi_hop_specific": MultiHopSpecificQuerySynthesizer,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deduplicate_questions(
    questions: list[dict], threshold: float = SIMILARITY_THRESHOLD
) -> list[dict]:
    """Remove near-duplicate questions using fuzzy string matching.

    Compares question text (user_input) pairwise. When two questions exceed
    the similarity threshold, the later one is dropped.
    """
    if not questions:
        return questions

    unique: list[dict] = []
    seen_texts: list[str] = []

    for q in questions:
        text = q.get("user_input", "").strip().lower()
        if not text:
            continue

        is_dup = False
        for existing in seen_texts:
            ratio = SequenceMatcher(None, text, existing).ratio()
            if ratio >= threshold:
                is_dup = True
                logger.info(
                    "Dropping duplicate question (similarity=%.2f): %s",
                    ratio,
                    text[:80],
                )
                break

        if not is_dup:
            unique.append(q)
            seen_texts.append(text)

    return unique


def _row_to_dict(row) -> dict:
    """Convert a Ragas testset DataFrame row to a plain dict."""
    return {
        "user_input": row.get("user_input", ""),
        "reference": row.get("reference", ""),
        "reference_contexts": row.get("reference_contexts", []),
        "synthesizer_name": row.get("synthesizer_name", ""),
    }


def _partition_list(items: list, n: int) -> list[list]:
    """Split *items* into *n* roughly equal partitions (round-robin)."""
    partitions: list[list] = [[] for _ in range(n)]
    for i, item in enumerate(items):
        partitions[i % n].append(item)
    return [p for p in partitions if p]


def build_query_distribution(dist_config: dict[str, float], llm=None):
    """Build a Ragas QueryDistribution from a {name: weight} dict."""
    distribution = []
    for name, weight in dist_config.items():
        cls = SYNTHESIZER_MAP.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown query type: {name}. Valid types: {list(SYNTHESIZER_MAP.keys())}"
            )
        distribution.append((cls(llm=llm), weight))
    return distribution


_async_openai_client: AsyncOpenAI | None = None
_sync_openai_client: OpenAI | None = None


def _get_async_openai() -> AsyncOpenAI:
    global _async_openai_client
    if _async_openai_client is None:
        _async_openai_client = AsyncOpenAI()
    return _async_openai_client


def _get_sync_openai() -> OpenAI:
    global _sync_openai_client
    if _sync_openai_client is None:
        _sync_openai_client = OpenAI()
    return _sync_openai_client


async def close_openai_clients() -> None:
    """Close module-level OpenAI clients. Call during app shutdown."""
    global _async_openai_client, _sync_openai_client
    if _async_openai_client is not None:
        await _async_openai_client.close()
        _async_openai_client = None
    if _sync_openai_client is not None:
        _sync_openai_client.close()
        _sync_openai_client = None


def _build_llm_and_embeddings():
    sync_client = _get_sync_openai()
    llm = llm_factory(DEFAULT_EVAL_MODEL, client=sync_client, max_tokens=DEFAULT_EVAL_MAX_TOKENS)
    embeddings = embedding_factory(
        "openai", model=DEFAULT_EVAL_EMBEDDING, client=sync_client
    )
    return llm, embeddings, sync_client


# ---------------------------------------------------------------------------
# Knowledge-graph helpers
# ---------------------------------------------------------------------------

def _chunks_hash(chunks: list[str]) -> str:
    """Return a stable hash of chunk contents for cache invalidation."""
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk.encode("utf-8"))
    return h.hexdigest()[:16]


def _load_kg_safe(tmp_path: str) -> KnowledgeGraph:
    """Load a KnowledgeGraph from a JSON file, removing dangling relationships.

    Ragas' CustomNodeFilter removes low-quality nodes but doesn't clean up
    relationships that reference those removed nodes. On reload, KnowledgeGraph.load
    raises KeyError when a relationship references a missing node ID.
    This function patches the JSON to strip dangling relationships before loading.
    """
    try:
        return KnowledgeGraph.load(tmp_path)
    except KeyError:
        logger.warning("KG JSON has dangling relationships — patching before load")
        import json as _json
        data = _json.loads(Path(tmp_path).read_text(encoding="utf-8"))
        node_ids = {n["id"] for n in data.get("nodes", [])}
        original_rel_count = len(data.get("relationships", []))
        data["relationships"] = [
            r for r in data.get("relationships", [])
            if r.get("source") in node_ids and r.get("target") in node_ids
        ]
        removed = original_rel_count - len(data["relationships"])
        logger.info("Removed %d dangling relationships from KG JSON", removed)
        patched_path = tmp_path + ".patched"
        Path(patched_path).write_text(_json.dumps(data), encoding="utf-8")
        try:
            return KnowledgeGraph.load(patched_path)
        finally:
            Path(patched_path).unlink(missing_ok=True)


def load_cached_kg(
    project_id: int,
    chunks: list[str],
    *,
    allow_partial: bool = False,
    kg_source: str = "chunks",
) -> tuple[KnowledgeGraph, int] | KnowledgeGraph | None:
    """Return a cached KG from the database if one exists.

    When *allow_partial* is False (default), only complete KGs are returned
    (as a plain ``KnowledgeGraph``).  Partial KGs are ignored.

    When *allow_partial* is True, returns a ``(KnowledgeGraph, completed_steps)``
    tuple for both complete and partial KGs so the caller can resume from the
    checkpoint.  Returns ``None`` if nothing is cached at all.
    """
    h = _chunks_hash(chunks)
    db = get_db()
    row = db.execute(
        "SELECT kg_json, is_complete, completed_steps, chunks_hash FROM knowledge_graphs "
        "WHERE project_id = ? AND chunks_hash = ? AND kg_source = ?",
        (project_id, h, kg_source),
    ).fetchone()
    if row is None and allow_partial:
        # Chunks hash may differ (e.g. row ordering without ORDER BY, or
        # sampling differences).  For resume we only need project_id since
        # save_kg_to_db keeps at most one row per project+source.
        # Also match KGs that are marked complete but have fewer steps than
        # the current pipeline (e.g. 6-step KG in a 7-step pipeline).
        row = db.execute(
            "SELECT kg_json, is_complete, completed_steps, chunks_hash FROM knowledge_graphs "
            "WHERE project_id = ? AND kg_source = ? AND (is_complete = FALSE OR completed_steps < 11)",
            (project_id, kg_source),
        ).fetchone()
        if row is not None:
            logger.warning(
                "Chunks hash mismatch for project %d (expected %s, got %s) "
                "— resuming partial KG anyway",
                project_id, h, row["chunks_hash"],
            )
    if row is None:
        return None

    if not row["is_complete"] and not allow_partial:
        logger.info(
            "Found partial KG checkpoint for project %d (step %d) — will resume",
            project_id,
            row["completed_steps"],
        )
        # Fall through to return partial when allow_partial would be set by caller
        # For backwards compat, return None here — callers that want resume
        # should pass allow_partial=True.
        return None

    logger.info(
        "Loading %s knowledge graph (source=%s) for project %d from DB",
        "complete" if row["is_complete"] else f"partial (step {row['completed_steps']})",
        kg_source,
        project_id,
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", errors="replace") as f:
        f.write(row["kg_json"])
        tmp_path = f.name
    try:
        kg = _load_kg_safe(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if allow_partial:
        return kg, row["completed_steps"]
    return kg


def save_kg_to_db(
    kg: KnowledgeGraph,
    project_id: int,
    chunks: list[str],
    *,
    is_complete: bool = True,
    completed_steps: int = 11,
    total_steps: int = 11,
    chunk_config_id: int | None = None,
    kg_source: str = "chunks",
) -> None:
    """Persist a KG to the database, replacing any stale entry for this project+source."""
    h = _chunks_hash(chunks)
    # Serialize KG via its save method to get the JSON string.
    with tempfile.NamedTemporaryFile(mode="r", suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        kg.save(tmp_path)
        kg_json = Path(tmp_path).read_text(encoding="utf-8")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    import db.init as _db
    conn = _db.get_thread_db()
    try:
        # Remove old entry for this project+source (content may have changed).
        conn.execute("DELETE FROM knowledge_graphs WHERE project_id = ? AND kg_source = ?", (project_id, kg_source))
        conn.execute(
            "INSERT INTO knowledge_graphs "
            "(project_id, chunks_hash, chunk_config_id, kg_json, num_nodes, num_chunks, is_complete, completed_steps, total_steps, last_heartbeat, kg_source) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {NOW_SQL}, ?)",
            (project_id, h, chunk_config_id, kg_json, len(kg.nodes), len(chunks), is_complete, completed_steps, total_steps, kg_source),
        )
        conn.commit()
    finally:
        conn.close()
    status = "complete" if is_complete else f"partial ({completed_steps}/{total_steps})"
    logger.info("Saved %s KG (source=%s) for project %d to DB (%d nodes)", status, kg_source, project_id, len(kg.nodes))


def delete_kg_from_db(project_id: int, kg_source: str = "chunks") -> bool:
    """Delete the cached KG for a project+source. Returns True if a row was deleted."""
    db = get_db()
    cursor = db.execute(
        "DELETE FROM knowledge_graphs WHERE project_id = ? AND kg_source = ?",
        (project_id, kg_source),
    )
    db.commit()
    return cursor.rowcount > 0


def update_heartbeat(project_id: int, kg_source: str = "chunks") -> None:
    """Touch the heartbeat timestamp for the KG build of a project+source."""
    import db.init as _db
    conn = _db.get_thread_db()
    try:
        conn.execute(
            f"UPDATE knowledge_graphs SET last_heartbeat = {NOW_SQL} "
            "WHERE project_id = ? AND kg_source = ?",
            (project_id, kg_source),
        )
        conn.commit()
    finally:
        conn.close()


_HEARTBEAT_STALE_MINUTES = 5


def get_kg_info(project_id: int, kg_source: str = "chunks") -> dict | None:
    """Return metadata about the cached KG for a project+source (without the full JSON).

    Includes a ``heartbeat_stale`` flag: True when the KG is partial and the
    last heartbeat is older than 5 minutes (likely a dead build).
    """
    db = get_db()
    row = db.execute(
        "SELECT id, project_id, chunks_hash, chunk_config_id, num_nodes, num_chunks, "
        "is_complete, completed_steps, total_steps, last_heartbeat, created_at "
        "FROM knowledge_graphs WHERE project_id = ? AND kg_source = ?",
        (project_id, kg_source),
    ).fetchone()
    if row is None:
        return None
    info = dict(row)
    # Normalize old KGs to the new 7-step pipeline
    info["total_steps"] = 11
    if info["completed_steps"] < 7:
        info["is_complete"] = False
    # Determine if the build looks stale (partial + heartbeat too old)
    if not info["is_complete"] and info.get("last_heartbeat"):
        from datetime import datetime, timedelta
        try:
            hb = info["last_heartbeat"]
            # psycopg2 returns datetime objects; SQLite returns strings
            if isinstance(hb, str):
                hb = datetime.strptime(hb, "%Y-%m-%d %H:%M:%S")
            info["heartbeat_stale"] = datetime.now() - hb > timedelta(minutes=_HEARTBEAT_STALE_MINUTES)
        except (ValueError, TypeError):
            info["heartbeat_stale"] = True
    else:
        info["heartbeat_stale"] = not info["is_complete"]  # no heartbeat at all = stale
    return info


_KG_BATCH_SIZE = KG_BATCH_SIZE  # max chunks per apply_transforms call to avoid Ragas deadlock


def _apply_transform_batched(
    kg: KnowledgeGraph,
    transform,
    batch_size: int = _KG_BATCH_SIZE,
    project_id: int | None = None,
    stage_name: str | None = None,
    overlap_max_nodes: int | None = 500,
    kg_source: str = "chunks",
) -> None:
    """Apply a transform to a KG in batches to work around Ragas hanging
    when the number of nodes is large (>~100).

    For transforms that operate per-node (HeadlinesExtractor,
    KeyphrasesExtractor) we split the KG nodes into batches, apply the
    transform to each mini-KG, then merge the results back.

    For global transforms (HeadlineSplitter, OverlapScoreBuilder) we run
    on the full KG since they don't make LLM calls.
    """
    from ragas.run_config import RunConfig

    needs_llm = isinstance(transform, (HeadlinesExtractor, KeyphrasesExtractor, SummaryExtractor, CustomNodeFilter, ThemesExtractor, NERExtractor, CombinedNodeExtractor, EmbeddingExtractor))

    # OverlapScoreBuilder is O(n² × k²) — cap node count to avoid multi-hour runs.
    # With k=10 keyphrases per node, approximate time estimates:
    #   250 nodes  → ~3M comparisons  → ~1 min
    #   500 nodes  → ~12M comparisons → ~3-5 min
    #   750 nodes  → ~28M comparisons → ~8-12 min
    #  1000 nodes  → ~50M comparisons → ~15-20 min
    #  1500 nodes  → ~112M comparisons → ~35-45 min
    #  2000 nodes  → ~200M comparisons → ~60-90 min
    if isinstance(transform, OverlapScoreBuilder) and overlap_max_nodes and len(kg.nodes) > overlap_max_nodes:
        import random
        logger.warning(
            "OverlapScoreBuilder: %d nodes exceeds cap of %d — sampling down",
            len(kg.nodes), overlap_max_nodes,
        )
        sampled = random.sample(list(kg.nodes), overlap_max_nodes)
        mini_kg = KnowledgeGraph()
        mini_kg.nodes = sampled
        apply_transforms(mini_kg, transforms=[transform], run_config=RunConfig(max_workers=16))
        # Copy relationships back to the main KG and restore all nodes
        for rel in mini_kg.relationships:
            kg.relationships.append(rel)
        return

    if not needs_llm or len(kg.nodes) <= batch_size:
        apply_transforms(kg, transforms=[transform], run_config=RunConfig(max_workers=16))
        return

    # Process in batches — build a mini KG per batch, apply, collect nodes.
    all_nodes = list(kg.nodes)
    total_nodes = len(all_nodes)
    total_batches = (total_nodes + batch_size - 1) // batch_size
    result_nodes = []
    for batch_idx, start in enumerate(range(0, total_nodes, batch_size)):
        batch_nodes = all_nodes[start : start + batch_size]
        mini_kg = KnowledgeGraph()
        mini_kg.nodes = batch_nodes
        logger.info(
            "  Batch %d/%d (%d–%d of %d nodes)",
            batch_idx + 1,
            total_batches,
            start,
            min(start + batch_size, total_nodes),
            total_nodes,
        )
        if project_id is not None and stage_name:
            update_progress(
                project_id,
                kg_source=kg_source,
                stage=stage_name,
                batch_current=batch_idx + 1,
                batch_total=total_batches,
                nodes_processed=start,
                nodes_total=total_nodes,
            )
            update_heartbeat(project_id)
        apply_transforms(mini_kg, transforms=[transform], run_config=RunConfig(max_workers=16))
        result_nodes.extend(mini_kg.nodes)

    # Final update showing all nodes processed
    if project_id is not None and stage_name:
        update_progress(
            project_id,
            kg_source=kg_source,
            stage=stage_name,
            batch_current=total_batches,
            batch_total=total_batches,
            nodes_processed=total_nodes,
            nodes_total=total_nodes,
        )

    kg.nodes = result_nodes


def build_knowledge_graph(
    chunks: list[str],
    llm=None,
    embeddings=None,
    project_id: int | None = None,
    overlap_max_nodes: int | None = 500,
    chunk_config_id: int | None = None,
    kg_source: str = "chunks",
    fast_mode: bool = False,
) -> KnowledgeGraph:
    """Build a KnowledgeGraph from text chunks and apply transforms.

    When *project_id* is provided the KG is cached in the database. Subsequent
    calls with the same project and chunk content return the cached version
    instantly.
    """
    # Check for complete or partial cached KG.
    # Fast mode never resumes from a partial normal-mode checkpoint (different
    # step count), but does return a fully complete KG immediately.
    resume_from_step = 0
    if project_id is not None:
        cached = load_cached_kg(
            project_id, chunks,
            allow_partial=not fast_mode,  # no partial resume in fast mode
            kg_source=kg_source,
        )
        if cached is not None:
            if fast_mode:
                # allow_partial=False: cached is a plain KnowledgeGraph
                update_progress(project_id, kg_source=kg_source, stage="kg_loaded_from_cache")
                return cached  # type: ignore[return-value]
            kg, cached_steps = cached  # type: ignore[misc]
            if cached_steps >= 11:
                # Fully complete — return immediately
                update_progress(project_id, kg_source=kg_source, stage="kg_loaded_from_cache")
                return kg
            # Partial checkpoint — resume from where we left off
            resume_from_step = cached_steps
            logger.info(
                "Resuming KG build for project %d from step %d/11 (%d nodes)",
                project_id, resume_from_step, len(kg.nodes),
            )
            update_progress(project_id, kg_source=kg_source, stage="kg_resuming_from_checkpoint")

    if llm is None or embeddings is None:
        llm, embeddings, _ = _build_llm_and_embeddings()

    if resume_from_step == 0:
        kg = KnowledgeGraph()
        for i, chunk in enumerate(chunks):
            kg.nodes.append(
                Node(
                    type=NodeType.DOCUMENT,
                    properties={
                        "page_content": chunk,
                        "document_metadata": {"chunk_id": i},
                    },
                )
            )

    # Run transforms one-by-one so we can report progress per step.
    # After each step, save a checkpoint so interrupted builds can resume.
    #
    # fast_mode uses a 7-step pipeline that replaces 5 separate LLM rounds with
    # a single CombinedNodeExtractor call (keyphrases + summary + themes +
    # entities + filter in one LLM call per node).
    if fast_mode:
        from config import DEFAULT_EVAL_MODEL
        _fast_model = DEFAULT_EVAL_MODEL
        transform_steps = [
            ("kg_extracting_headlines", HeadlinesExtractor(llm=llm)),
            ("kg_splitting_headlines", HeadlineSplitter(min_tokens=100, max_tokens=500)),
            ("kg_combined_extraction", CombinedNodeExtractor(model=_fast_model)),
            # inline filter applied after kg_combined_extraction (see loop below)
            ("kg_building_overlap", OverlapScoreBuilder(
                property_name="keyphrases",
                new_property_name="overlap_score",
                threshold=0.1,
                distance_threshold=0.9,
            )),
            ("kg_embedding_summaries", EmbeddingExtractor(
                embedding_model=embeddings,
                property_name="summary_embedding",
                embed_property_name="summary",
            )),
            ("kg_building_summary_similarity", CosineSimilarityBuilder(
                property_name="summary_embedding",
                new_property_name="summary_similarity",
                threshold=0.7,
            )),
            ("kg_building_entity_overlap", OverlapScoreBuilder(
                property_name="entities",
                new_property_name="entity_overlap",
                threshold=0.01,
            )),
        ]
    else:
        transform_steps = [
            ("kg_extracting_headlines", HeadlinesExtractor(llm=llm)),
            ("kg_splitting_headlines", HeadlineSplitter(min_tokens=100, max_tokens=500)),
            ("kg_extracting_keyphrases", KeyphrasesExtractor(llm=llm, property_name="keyphrases", max_num=10)),
            ("kg_building_overlap", OverlapScoreBuilder(
                property_name="keyphrases",
                new_property_name="overlap_score",
                threshold=0.1,
                distance_threshold=0.9,
            )),
            ("kg_extracting_summaries", SummaryExtractor(llm=llm)),
            ("kg_filtering_nodes", CustomNodeFilter(llm=llm)),
            ("kg_embedding_summaries", EmbeddingExtractor(
                embedding_model=embeddings,
                property_name="summary_embedding",
                embed_property_name="summary",
            )),
            ("kg_extracting_themes", ThemesExtractor(llm=llm)),
            ("kg_extracting_entities", NERExtractor(llm=llm)),
            ("kg_building_summary_similarity", CosineSimilarityBuilder(
                property_name="summary_embedding",
                new_property_name="summary_similarity",
                threshold=0.7,
            )),
            ("kg_building_entity_overlap", OverlapScoreBuilder(
                property_name="entities",
                new_property_name="entity_overlap",
                threshold=0.01,
            )),
        ]
    completed_steps = resume_from_step
    for idx, (stage_name, transform) in enumerate(transform_steps):
        if idx < resume_from_step:
            logger.info("Skipping already-completed step %d: %s", idx + 1, stage_name)
            continue
        if project_id is not None:
            update_progress(
                project_id,
                kg_source=kg_source,
                stage=stage_name,
                completed_steps=completed_steps,
                total_steps=len(transform_steps),
            )
            update_heartbeat(project_id, kg_source=kg_source)
        logger.info("KG transform: %s (%d nodes)", stage_name, len(kg.nodes))
        try:
            _apply_transform_batched(kg, transform, project_id=project_id, stage_name=stage_name, overlap_max_nodes=overlap_max_nodes, kg_source=kg_source)
            # Fast mode: after combined extraction, filter nodes marked keep=False
            if fast_mode and stage_name == "kg_combined_extraction":
                before_filter = len(kg.nodes)
                remove_ids = {n.id for n in kg.nodes if not n.properties.get("_fast_keep", True)}
                if remove_ids:
                    kg.nodes = [n for n in kg.nodes if n.id not in remove_ids]
                    kg.relationships = [
                        r for r in kg.relationships
                        if r.source.id not in remove_ids and r.target.id not in remove_ids
                    ]
                    logger.info(
                        "Fast-mode filter: removed %d/%d nodes",
                        before_filter - len(kg.nodes), before_filter,
                    )

            # After CustomNodeFilter removes nodes, clean up any relationships that
            # now reference missing node IDs to prevent KeyError on KG reload.
            if stage_name == "kg_filtering_nodes" and kg.relationships:
                node_ids = {n.id for n in kg.nodes}
                before = len(kg.relationships)
                kg.relationships = [
                    r for r in kg.relationships
                    if r.source.id in node_ids and r.target.id in node_ids
                ]
                removed = before - len(kg.relationships)
                if removed:
                    logger.info("Removed %d dangling relationships after node filtering", removed)
            completed_steps += 1
            # Save checkpoint after each step so we can resume on crash
            if project_id is not None:
                save_kg_to_db(
                    kg,
                    project_id,
                    chunks,
                    is_complete=(completed_steps == len(transform_steps)),
                    completed_steps=completed_steps,
                    total_steps=len(transform_steps),
                    chunk_config_id=chunk_config_id,
                    kg_source=kg_source,
                )
                if completed_steps < len(transform_steps):
                    logger.info(
                        "Saved checkpoint after step %d/%d for project %d",
                        completed_steps, len(transform_steps), project_id,
                    )
        except Exception:
            logger.exception(
                "KG transform '%s' failed after %d/%d steps — saving partial KG",
                stage_name,
                completed_steps,
                len(transform_steps),
            )
            if project_id is not None and completed_steps > 0:
                save_kg_to_db(
                    kg,
                    project_id,
                    chunks,
                    is_complete=False,
                    completed_steps=completed_steps,
                    total_steps=len(transform_steps),
                    chunk_config_id=chunk_config_id,
                    kg_source=kg_source,
                )
            raise

    return kg


def build_kg_standalone(
    chunk_config_id: int,
    project_id: int,
    overlap_max_nodes: int | None = 500,
    fast_mode: bool = False,
) -> dict:
    """Build a KG from chunks in the DB and cache it.

    Designed to run in a background thread.  Uses the in-memory progress
    store so the frontend can poll for status.
    """
    import db.init as _db

    conn = _db.get_thread_db()
    rows = conn.execute(
        "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
        (chunk_config_id,),
    ).fetchall()
    chunks = [r["content"] for r in rows]
    if not chunks:
        raise ValueError("No chunks found for chunk_config_id=%d" % chunk_config_id)

    set_progress(project_id, {
        "stage": "building_knowledge_graph",
        "kg_building": True,
        "total_chunks": len(chunks),
    }, kg_source="chunks")

    try:
        kg = build_knowledge_graph(chunks, project_id=project_id, overlap_max_nodes=overlap_max_nodes, chunk_config_id=chunk_config_id, fast_mode=fast_mode)
        clear_progress(project_id, kg_source="chunks")
        return {
            "num_nodes": len(kg.nodes),
            "num_chunks": len(chunks),
        }
    except Exception:
        clear_progress(project_id, kg_source="chunks")
        raise


def _fetch_document_texts(project_id: int) -> list[str]:
    """Fetch full document texts for a project from the DB."""
    import db.init as _db
    conn = _db.get_thread_db()
    rows = conn.execute(
        "SELECT content FROM documents WHERE project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()
    return [r["content"] for r in rows]


def build_kg_standalone_from_documents(
    project_id: int,
    overlap_max_nodes: int | None = 500,
) -> dict:
    """Build a document-level KG from full document texts in the DB.

    Uses each document's full text as a KG input node. The HeadlineSplitter
    step will further divide documents by section headings. Better suited for
    Graph RAG question generation than chunk-based KGs since it avoids
    artificial chunk boundary splits.

    Designed to run in a background thread.
    """
    doc_texts = _fetch_document_texts(project_id)
    if not doc_texts:
        raise ValueError("No documents found for project_id=%d" % project_id)

    set_progress(project_id, {
        "stage": "building_knowledge_graph",
        "kg_building": True,
        "total_chunks": len(doc_texts),
    }, kg_source="documents")

    try:
        kg = build_knowledge_graph(
            doc_texts,
            project_id=project_id,
            overlap_max_nodes=overlap_max_nodes,
            kg_source="documents",
        )
        clear_progress(project_id, kg_source="documents")
        return {
            "num_nodes": len(kg.nodes),
            "num_chunks": len(doc_texts),
        }
    except Exception:
        clear_progress(project_id, kg_source="documents")
        raise


def rebuild_kg_links(
    project_id: int,
    overlap_max_nodes: int | None = 500,
    kg_source: str = "chunks",
) -> dict:
    """Reload a complete/partial KG, strip existing relationships, and re-run
    only the OverlapScoreBuilder with new parameters.

    Much faster than a full rebuild since it skips headline and keyphrase
    extraction (the expensive LLM steps).
    """
    from ragas.run_config import RunConfig

    db = get_db()
    row = db.execute(
        "SELECT kg_json, chunks_hash, chunk_config_id, completed_steps "
        "FROM knowledge_graphs WHERE project_id = ? AND kg_source = ?",
        (project_id, kg_source),
    ).fetchone()
    if row is None:
        raise ValueError(f"No knowledge graph found for project {project_id}")
    if (row["completed_steps"] or 0) < 3:
        raise ValueError(
            f"KG only has {row['completed_steps']}/11 steps — keyphrases must be "
            "extracted before links can be built"
        )

    set_progress(project_id, {
        "stage": "kg_building_overlap",
        "kg_building": True,
    }, kg_source=kg_source)

    try:
        # Load KG from DB
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(row["kg_json"])
            tmp_path = f.name
        try:
            kg = _load_kg_safe(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Strip all existing relationships
        old_count = len(kg.relationships)
        kg.relationships.clear()
        logger.info(
            "Rebuilding links for project %d: removed %d old relationships, "
            "%d nodes, overlap_max_nodes=%s",
            project_id, old_count, len(kg.nodes), overlap_max_nodes,
        )

        update_progress(project_id, kg_source=kg_source, stage="kg_building_overlap")
        update_heartbeat(project_id, kg_source=kg_source)

        transform = OverlapScoreBuilder(
            property_name="keyphrases",
            new_property_name="overlap_score",
            threshold=0.1,
            distance_threshold=0.9,
        )
        _apply_transform_batched(
            kg, transform,
            project_id=project_id,
            stage_name="kg_building_overlap",
            overlap_max_nodes=overlap_max_nodes,
            kg_source=kg_source,
        )

        # Get chunks for hash (needed by save_kg_to_db)
        chunk_config_id = row["chunk_config_id"]
        if chunk_config_id:
            import db.init as _db
            conn = _db.get_db()
            chunk_rows = conn.execute(
                "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
                (chunk_config_id,),
            ).fetchall()
            chunks = [r["content"] for r in chunk_rows]
        else:
            # Fallback: use existing hash, save with empty chunks list
            chunks = []

        # Overlap is step 4; later steps (5-9) may or may not have been run
        # previously.  Preserve the higher step count if present.
        prev_steps = row["completed_steps"] or 4
        new_steps = max(4, prev_steps)
        save_kg_to_db(
            kg, project_id, chunks,
            is_complete=(new_steps >= 11),
            completed_steps=new_steps,
            total_steps=11,
            chunk_config_id=chunk_config_id,
            kg_source=kg_source,
        )

        logger.info(
            "Rebuilt links for project %d: %d relationships",
            project_id, len(kg.relationships),
        )
        return {
            "num_nodes": len(kg.nodes),
            "num_relationships": len(kg.relationships),
        }
    finally:
        clear_progress(project_id, kg_source=kg_source)


# ---------------------------------------------------------------------------
# Incremental KG update helpers
# ---------------------------------------------------------------------------


def _diff_chunks(
    old_chunks: list[str],
    new_chunks: list[str],
) -> tuple[list[str], list[int], dict[int, int]]:
    """Compare old and new chunk lists to identify additions and removals.

    Returns:
        added_chunks: list of chunk contents that are new
        removed_old_indices: indices into *old_chunks* that no longer exist
        old_to_new_map: mapping from old index → new index for surviving chunks
    """
    old_hashes: dict[str, list[int]] = {}
    for i, c in enumerate(old_chunks):
        h = hashlib.sha256(c.encode("utf-8")).hexdigest()[:16]
        old_hashes.setdefault(h, []).append(i)

    new_hashes: dict[str, list[int]] = {}
    for i, c in enumerate(new_chunks):
        h = hashlib.sha256(c.encode("utf-8")).hexdigest()[:16]
        new_hashes.setdefault(h, []).append(i)

    # Determine which old indices survive and map to new indices
    old_to_new_map: dict[int, int] = {}
    matched_old: set[int] = set()
    for h, new_indices in new_hashes.items():
        old_indices = list(old_hashes.get(h, []))
        for ni in new_indices:
            if old_indices:
                oi = old_indices.pop(0)
                old_to_new_map[oi] = ni
                matched_old.add(oi)

    removed_old_indices = [i for i in range(len(old_chunks)) if i not in matched_old]

    # Added chunks = new chunks whose hash had no remaining old match
    matched_new = set(old_to_new_map.values())
    added_chunks = [new_chunks[i] for i in range(len(new_chunks)) if i not in matched_new]

    return added_chunks, removed_old_indices, old_to_new_map


def incremental_update_kg(
    project_id: int,
    chunk_config_id: int,
    overlap_max_nodes: int | None = 500,
    kg_source: str = "chunks",
) -> dict:
    """Incrementally update a cached KG when documents are added or removed.

    Instead of rebuilding all 11 transform steps from scratch, this:
    1. Loads the existing KG
    2. Removes nodes for deleted chunks
    3. Runs per-node transforms only on new chunks
    4. Merges new nodes into the existing KG
    5. Re-runs cross-node link transforms on the full graph
    6. Saves with the updated chunks hash

    Designed to run in a background thread.
    """
    import db.init as _db
    from ragas.run_config import RunConfig

    conn = _db.get_thread_db()

    # Load current chunks from DB
    chunk_rows = conn.execute(
        "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
        (chunk_config_id,),
    ).fetchall()
    new_chunks = [r["content"] for r in chunk_rows]
    if not new_chunks:
        raise ValueError("No chunks found for chunk_config_id=%d" % chunk_config_id)

    # Load existing KG
    row = conn.execute(
        "SELECT kg_json, chunks_hash, completed_steps FROM knowledge_graphs "
        "WHERE project_id = ? AND kg_source = ?",
        (project_id, kg_source),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"No existing knowledge graph for project {project_id} — use full build instead"
        )

    set_progress(project_id, {
        "stage": "kg_diffing_chunks",
        "kg_building": True,
    }, kg_source=kg_source)

    # Reconstruct old chunks from the stored hash by loading from the DB
    # We need the actual old chunks to diff. The KG stores chunk content in node properties.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", errors="replace") as f:
        f.write(row["kg_json"])
        tmp_path = f.name
    try:
        kg = _load_kg_safe(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Extract old chunks from KG node properties (preserving order by chunk_id)
    old_chunk_nodes = []
    for node in kg.nodes:
        props = node.properties if hasattr(node, "properties") else {}
        meta = props.get("document_metadata", {})
        chunk_id = meta.get("chunk_id")
        content = props.get("page_content", "")
        if chunk_id is not None and content:
            old_chunk_nodes.append((chunk_id, content, node))

    old_chunk_nodes.sort(key=lambda x: x[0])
    old_chunks = [content for _, content, _ in old_chunk_nodes]

    # Check if chunks actually changed
    new_hash = _chunks_hash(new_chunks)
    if new_hash == row["chunks_hash"]:
        logger.info("Chunks unchanged for project %d — no update needed", project_id)
        clear_progress(project_id, kg_source=kg_source)
        return {"status": "unchanged", "num_nodes": len(kg.nodes)}

    added_chunks, removed_old_indices, old_to_new_map = _diff_chunks(old_chunks, new_chunks)
    logger.info(
        "Incremental KG update for project %d: %d added, %d removed, %d kept",
        project_id, len(added_chunks), len(removed_old_indices),
        len(old_to_new_map),
    )

    if not added_chunks and not removed_old_indices:
        logger.info("No effective changes detected for project %d", project_id)
        clear_progress(project_id, kg_source=kg_source)
        return {"status": "unchanged", "num_nodes": len(kg.nodes)}

    try:
        # --- Step 1: Remove nodes for deleted chunks ---
        if removed_old_indices:
            update_progress(project_id, kg_source=kg_source, stage="kg_removing_old_nodes")
            removed_set = set(removed_old_indices)
            # Find nodes to remove by their chunk_id
            nodes_to_remove = set()
            for chunk_id, _, node in old_chunk_nodes:
                if chunk_id in removed_set:
                    nodes_to_remove.add(node.id)

            # Also remove any child nodes (e.g. headline-split nodes) that
            # reference a removed parent.  Walk the node list looking for
            # nodes whose page_content is a substring of removed content.
            # (Ragas HeadlineSplitter creates child nodes but doesn't track
            # parent references in metadata, so we use id membership.)
            original_count = len(kg.nodes)
            kg.nodes = [n for n in kg.nodes if n.id not in nodes_to_remove]

            # Remove relationships that reference removed nodes
            kg.relationships = [
                r for r in kg.relationships
                if r.source.id not in nodes_to_remove and r.target.id not in nodes_to_remove
            ]
            logger.info(
                "Removed %d nodes (%d → %d), cleaned relationships",
                original_count - len(kg.nodes), original_count, len(kg.nodes),
            )

        # --- Step 2: Re-index chunk_ids on surviving nodes ---
        update_progress(project_id, kg_source=kg_source, stage="kg_reindexing_nodes")
        for chunk_id, _, node in old_chunk_nodes:
            if chunk_id in old_to_new_map:
                props = node.properties if hasattr(node, "properties") else {}
                meta = props.get("document_metadata", {})
                meta["chunk_id"] = old_to_new_map[chunk_id]
                props["document_metadata"] = meta

        # --- Step 3: Process new chunks through per-node transforms ---
        if added_chunks:
            update_progress(project_id, kg_source=kg_source, stage="kg_processing_new_chunks")
            llm, embeddings, _ = _build_llm_and_embeddings()

            # Create nodes for new chunks
            # Assign chunk_ids based on their position in new_chunks
            matched_new_indices = set(old_to_new_map.values())
            new_chunk_indices = [i for i in range(len(new_chunks)) if i not in matched_new_indices]

            new_kg = KnowledgeGraph()
            for idx, chunk in zip(new_chunk_indices, added_chunks):
                new_kg.nodes.append(
                    Node(
                        type=NodeType.DOCUMENT,
                        properties={
                            "page_content": chunk,
                            "document_metadata": {"chunk_id": idx},
                        },
                    )
                )

            # Run per-node transforms on new nodes only
            per_node_transforms = [
                ("kg_extracting_headlines", HeadlinesExtractor(llm=llm)),
                ("kg_splitting_headlines", HeadlineSplitter(min_tokens=100, max_tokens=500)),
                ("kg_extracting_keyphrases", KeyphrasesExtractor(llm=llm, property_name="keyphrases", max_num=10)),
                ("kg_extracting_summaries", SummaryExtractor(llm=llm)),
                ("kg_filtering_nodes", CustomNodeFilter(llm=llm)),
                ("kg_embedding_summaries", EmbeddingExtractor(
                    embedding_model=embeddings,
                    property_name="summary_embedding",
                    embed_property_name="summary",
                )),
                ("kg_extracting_themes", ThemesExtractor(llm=llm)),
                ("kg_extracting_entities", NERExtractor(llm=llm)),
            ]

            for stage_name, transform in per_node_transforms:
                update_progress(project_id, kg_source=kg_source, stage=f"incremental_{stage_name}")
                update_heartbeat(project_id)
                logger.info("Incremental transform on new nodes: %s (%d nodes)", stage_name, len(new_kg.nodes))
                _apply_transform_batched(
                    new_kg, transform,
                    project_id=project_id,
                    stage_name=stage_name,
                    overlap_max_nodes=overlap_max_nodes,
                    kg_source=kg_source,
                )

            # Merge new nodes into existing KG
            logger.info("Merging %d new nodes into existing KG (%d nodes)", len(new_kg.nodes), len(kg.nodes))
            kg.nodes.extend(new_kg.nodes)

        # --- Step 4: Re-run cross-node link transforms ---
        update_progress(project_id, kg_source=kg_source, stage="kg_rebuilding_links")
        update_heartbeat(project_id)

        # Strip all existing relationships — they need to be rebuilt
        # since the node set changed
        old_rel_count = len(kg.relationships)
        kg.relationships.clear()
        logger.info("Cleared %d old relationships, rebuilding links for %d nodes", old_rel_count, len(kg.nodes))

        link_transforms = [
            ("kg_building_overlap", OverlapScoreBuilder(
                property_name="keyphrases",
                new_property_name="overlap_score",
                threshold=0.1,
                distance_threshold=0.9,
            )),
            ("kg_building_summary_similarity", CosineSimilarityBuilder(
                property_name="summary_embedding",
                new_property_name="summary_similarity",
                threshold=0.5,
            )),
            ("kg_building_entity_overlap", OverlapScoreBuilder(
                property_name="entities",
                new_property_name="entity_overlap",
                threshold=0.01,
            )),
        ]

        for stage_name, transform in link_transforms:
            update_progress(project_id, kg_source=kg_source, stage=stage_name)
            update_heartbeat(project_id, kg_source=kg_source)
            logger.info("Rebuilding links: %s", stage_name)
            _apply_transform_batched(
                kg, transform,
                project_id=project_id,
                stage_name=stage_name,
                overlap_max_nodes=overlap_max_nodes,
                kg_source=kg_source,
            )

        # --- Step 5: Save ---
        save_kg_to_db(
            kg, project_id, new_chunks,
            is_complete=True,
            completed_steps=11,
            total_steps=11,
            chunk_config_id=chunk_config_id,
            kg_source=kg_source,
        )

        logger.info(
            "Incremental KG update complete for project %d: %d nodes, %d relationships",
            project_id, len(kg.nodes), len(kg.relationships),
        )
        return {
            "status": "updated",
            "num_nodes": len(kg.nodes),
            "num_relationships": len(kg.relationships),
            "chunks_added": len(added_chunks),
            "chunks_removed": len(removed_old_indices),
        }
    finally:
        clear_progress(project_id, kg_source=kg_source)


def generate_personas_fast(
    chunks: list[str],
    num_personas: int = 3,
) -> list[dict]:
    """Generate personas via two lightweight LLM calls covering all chunks.

    Step 1: Extract key topics/themes from ALL chunks (batched if needed).
    Step 2: Generate diverse personas from the topic summary.

    Much faster than the KG-based approach while still covering the full
    document scope.
    """
    client = OpenAI()

    # --- Step 1: Extract topics from all chunks in batches ---
    # gpt-4o-mini has a 128k context window; stay well under with ~80k chars per batch
    MAX_CHARS_PER_BATCH = PERSONA_MAX_CHARS_PER_BATCH
    batches: list[str] = []
    current_batch: list[str] = []
    current_len = 0
    for chunk in chunks:
        chunk_len = len(chunk) + 5  # +5 for separator
        if current_len + chunk_len > MAX_CHARS_PER_BATCH and current_batch:
            batches.append("\n---\n".join(current_batch))
            current_batch = []
            current_len = 0
        current_batch.append(chunk)
        current_len += chunk_len
    if current_batch:
        batches.append("\n---\n".join(current_batch))

    topic_summaries: list[str] = []
    for batch_text in batches:
        resp = client.chat.completions.create(
            model=DEFAULT_EVAL_MODEL,
            temperature=TESTGEN_TOPIC_TEMPERATURE,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert at identifying key topics and themes "
                        "in documents. Given document excerpts, list ALL distinct "
                        "topics, domains, and subject areas covered. Be thorough "
                        "— do not miss niche or specialized topics. "
                        "Return a concise bullet-point list, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Extract all key topics from these excerpts:\n\n{batch_text}",
                },
            ],
        )
        topic_summaries.append(resp.choices[0].message.content.strip())

    all_topics = "\n".join(topic_summaries)

    # --- Step 2: Generate personas from the combined topic overview ---
    response = client.chat.completions.create(
        model=DEFAULT_EVAL_MODEL,
        temperature=TESTGEN_PERSONA_TEMPERATURE,
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate test personas for a QA evaluation system. "
                    "Given a list of topics/themes from a document collection, "
                    "create diverse personas who would ask different types of "
                    "questions about this content. Ensure personas cover "
                    "different expertise levels, roles, and perspectives "
                    "relevant to the topics. "
                    "For each persona, also define a 'question_style' that "
                    "describes HOW they phrase questions (e.g. formal "
                    "technical queries, casual how-do-I questions, detailed "
                    "scenario-based questions, brief keyword searches, etc.). "
                    "Return ONLY a JSON array of objects with 'name', "
                    "'role_description', and 'question_style' keys. "
                    "No markdown, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on these topics covered in the documents, generate "
                    f"{num_personas} diverse personas:\n\n{all_topics}"
                ),
            },
        ],
    )
    text = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        parsed = _json.loads(text)
    except _json.JSONDecodeError:
        logger.error("LLM returned invalid JSON for persona generation: %s", text[:200])
        return []

    if not isinstance(parsed, list):
        logger.error("Expected JSON array from LLM, got %s", type(parsed).__name__)
        return []

    results: list[dict] = []
    for p in parsed[:num_personas]:
        if not isinstance(p, dict) or "name" not in p or "role_description" not in p:
            logger.warning("Skipping malformed persona entry: %s", p)
            continue
        results.append({
            "name": p["name"],
            "role_description": p["role_description"],
            "question_style": p.get("question_style", ""),
        })
    return results


def _enrich_with_question_styles(personas: list[Persona]) -> list[dict]:
    """Add question_style to Ragas personas via a single LLM call."""
    client = OpenAI()
    persona_list = _json.dumps([
        {"name": p.name, "role_description": p.role_description}
        for p in personas
    ])
    response = client.chat.completions.create(
        model=DEFAULT_EVAL_MODEL,
        temperature=TESTGEN_PERSONA_TEMPERATURE,
        messages=[
            {
                "role": "system",
                "content": (
                    "Given a list of test personas, add a 'question_style' to each "
                    "that describes HOW they phrase questions (e.g. formal "
                    "technical queries, casual how-do-I questions, detailed "
                    "scenario-based questions, brief keyword searches, etc.). "
                    "Return ONLY a JSON array with 'name', 'role_description', "
                    "and 'question_style' keys. No markdown, no explanation."
                ),
            },
            {"role": "user", "content": persona_list},
        ],
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, list):
            return [
                {
                    "name": p.get("name", ""),
                    "role_description": p.get("role_description", ""),
                    "question_style": p.get("question_style", ""),
                }
                for p in parsed
            ]
    except _json.JSONDecodeError:
        logger.error("Failed to parse question styles from LLM: %s", text[:200])
    # Fallback: return without styles
    return [
        {"name": p.name, "role_description": p.role_description, "question_style": ""}
        for p in personas
    ]


def _merge_persona_fields(p: dict) -> Persona:
    """Build a ragas Persona, folding question_style into role_description."""
    desc = p["role_description"]
    style = p.get("question_style", "").strip()
    if style:
        desc = f"{desc}. Question style: {style}"
    return Persona(name=p["name"], role_description=desc)


def generate_personas(
    chunks: list[str],
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    fast: bool = False,
    project_id: int | None = None,
) -> list[Persona]:
    """Generate personas from document chunks, or use custom-defined ones."""
    if custom_personas:
        return [_merge_persona_fields(p) for p in custom_personas]

    if fast:
        raw = generate_personas_fast(chunks, num_personas=num_personas)
        return [_merge_persona_fields(p) for p in raw]

    llm, embeddings, _ = _build_llm_and_embeddings()
    kg = build_knowledge_graph(chunks, llm=llm, embeddings=embeddings, project_id=project_id)

    # Ragas generate_personas_from_kg requires summary + summary_embedding
    # properties that our 4-step KG pipeline doesn't produce.  Check if the
    # KG has them; if not, fall back to the fast LLM-based approach.
    has_summaries = any(
        n.properties.get("summary_embedding") is not None
        for n in kg.nodes
    )
    if has_summaries:
        personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=num_personas)
    else:
        logger.info("KG nodes lack summary_embedding — using fast persona generation")
        raw = generate_personas_fast(chunks, num_personas=num_personas)
        return [_merge_persona_fields(p) for p in raw]
    return personas


# ---------------------------------------------------------------------------
# Single-worker batch functions (run inside ThreadPoolExecutor)
# ---------------------------------------------------------------------------


def _worker_generate_from_chunks(
    chunks: list[str],
    batch_size: int,
    query_distribution: dict[str, float] | None,
    project_id: int | None = None,
) -> list[dict]:
    """Worker: generate questions from a chunk subset."""
    llm, embeddings, _ = _build_llm_and_embeddings()
    generator = TestsetGenerator(llm=llm, embedding_model=embeddings)
    qd = build_query_distribution(query_distribution, llm=llm) if query_distribution else None

    testset = generator.generate_with_chunks(
        chunks=chunks,
        testset_size=batch_size,
        query_distribution=qd,
    )
    results = [_row_to_dict(row) for _, row in testset.to_pandas().iterrows()]
    if project_id is not None:
        increment_questions(project_id, len(results))
    return results


def _worker_generate_from_kg(
    kg: KnowledgeGraph,
    personas: list[Persona],
    batch_size: int,
    query_distribution: dict[str, float] | None,
    project_id: int | None = None,
) -> list[dict]:
    """Worker: generate questions from a shared KnowledgeGraph."""
    llm, embedding_model, _ = _build_llm_and_embeddings()
    generator = TestsetGenerator(
        knowledge_graph=kg,
        persona_list=personas,
        llm=llm,
        embedding_model=embedding_model,
    )
    qd = build_query_distribution(query_distribution, llm=llm) if query_distribution else None

    testset = generator.generate(testset_size=batch_size, query_distribution=qd)
    results = [_row_to_dict(row) for _, row in testset.to_pandas().iterrows()]
    if project_id is not None:
        increment_questions(project_id, len(results))
    return results


# ---------------------------------------------------------------------------
# Public generation functions
# ---------------------------------------------------------------------------


def generate_testset_from_chunks(
    chunks: list[str],
    testset_size: int = 10,
    personas: list[Persona] | None = None,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
    num_workers: int = 4,
    project_id: int | None = None,
) -> list[dict]:
    """Generate test questions from pre-chunked text using parallel workers.

    Chunks are partitioned across workers. Each worker independently generates
    questions from its chunk subset, giving natural diversity. Results are
    merged, deduplicated, and trimmed to *testset_size*.
    """
    # Adjust worker count so each worker has enough chunks.
    effective_workers = min(
        num_workers,
        max(1, len(chunks) // MIN_CHUNKS_PER_WORKER),
    )

    if effective_workers <= 1:
        # Fast path — single worker, no threading overhead.
        generate_size = int(testset_size * OVERGENERATE_FACTOR)
        results = _worker_generate_from_chunks(chunks, generate_size, query_distribution, project_id=project_id)
        results = _deduplicate_questions(results)
        return results[:testset_size]

    # Split chunks round-robin across workers.
    chunk_partitions = _partition_list(chunks, effective_workers)
    effective_workers = len(chunk_partitions)

    # Each worker over-generates its share.
    per_worker = int(math.ceil(testset_size * OVERGENERATE_FACTOR / effective_workers))

    logger.info(
        "Parallel chunk-based generation: %d workers × %d questions/worker "
        "(target %d after dedup)",
        effective_workers,
        per_worker,
        testset_size,
    )

    _shutdown_event.clear()
    _register_shutdown_handler()

    all_questions: list[dict] = []
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = [
            pool.submit(
                _worker_generate_from_chunks,
                partition,
                per_worker,
                query_distribution,
                project_id,
            )
            for partition in chunk_partitions
        ]
        for future in as_completed(futures):
            if _shutdown_event.is_set() or is_cancelled(project_id):
                for f in futures:
                    f.cancel()
                break
            try:
                all_questions.extend(future.result())
            except Exception:
                logger.exception("Worker failed during chunk-based generation")

    all_questions = _deduplicate_questions(all_questions)
    return all_questions[:testset_size]


def generate_testset_with_personas(
    chunks: list[str],
    testset_size: int = 10,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
    num_workers: int = 4,
    project_id: int | None = None,
    prebuilt_kg: "KnowledgeGraph | None" = None,
    fast_mode: bool = False,
) -> dict:
    """Generate test questions with persona information using parallel workers.

    The knowledge graph is built once (sequential), then generation is split
    across *num_workers* threads sharing the same KG and persona list.

    If *prebuilt_kg* is provided it is used directly and the KG build step is
    skipped entirely (used for KG-node sampling from an existing full KG).
    """
    llm, embeddings, _ = _build_llm_and_embeddings()

    if prebuilt_kg is not None:
        kg = prebuilt_kg
        logger.info(
            "Using pre-sampled KG (%d nodes) — skipping KG build", len(kg.nodes)
        )
    else:
        logger.info("Building knowledge graph from %d chunks...", len(chunks))
        if project_id is not None:
            update_progress(project_id, kg_source="testset", stage="building_knowledge_graph")
        kg = build_knowledge_graph(chunks, llm=llm, embeddings=embeddings, project_id=project_id, fast_mode=fast_mode)

    if project_id is not None:
        update_progress(project_id, kg_source="testset", stage="generating_personas")

    if custom_personas:
        personas = [_merge_persona_fields(p) for p in custom_personas]
    else:
        has_summaries = any(
            n.properties.get("summary_embedding") is not None
            for n in kg.nodes
        )
        if has_summaries:
            personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=num_personas)
        else:
            logger.info("KG nodes lack summary_embedding — using fast persona generation")
            raw = generate_personas_fast(chunks, num_personas=num_personas)
            personas = [_merge_persona_fields(p) for p in raw]

    if project_id is not None:
        update_progress(project_id, kg_source="testset", stage="generating_questions")

    effective_workers = max(1, min(num_workers, testset_size))

    if effective_workers <= 1:
        generate_size = int(testset_size * OVERGENERATE_FACTOR)
        questions = _worker_generate_from_kg(kg, personas, generate_size, query_distribution, project_id=project_id)
        questions = _deduplicate_questions(questions)
        questions = questions[:testset_size]
    else:
        per_worker = int(math.ceil(testset_size * OVERGENERATE_FACTOR / effective_workers))

        logger.info(
            "Parallel persona-based generation: %d workers × %d questions/worker "
            "(target %d after dedup)",
            effective_workers,
            per_worker,
            testset_size,
        )

        _shutdown_event.clear()
        _register_shutdown_handler()

        all_questions: list[dict] = []
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = [
                pool.submit(
                    _worker_generate_from_kg,
                    kg,
                    personas,
                    per_worker,
                    query_distribution,
                    project_id,
                )
                for _ in range(effective_workers)
            ]
            for future in as_completed(futures):
                if _shutdown_event.is_set() or is_cancelled(project_id):
                    for f in futures:
                        f.cancel()
                    break
                try:
                    all_questions.extend(future.result())
                except Exception:
                    logger.exception("Worker failed during persona-based generation")

        questions = _deduplicate_questions(all_questions)
        questions = questions[:testset_size]

    persona_list = [
        {"name": p.name, "role_description": p.role_description}
        for p in personas
    ]

    return {
        "personas": persona_list,
        "questions": questions,
    }


def _generate_category_questions_via_llm(
    chunks: list[str],
    category: str,
    count: int,
) -> list[dict]:
    """Generate questions for edge-case or out-of-KB categories using direct LLM calls.

    For 'edge': generates unusual, adversarial, or boundary-case questions
    based on the document content.
    For 'out_of_knowledge_base': generates plausible questions about topics
    NOT covered by the documents.
    """
    if count <= 0:
        return []

    client = OpenAI()

    # Build a summary of what the KB covers from a sample of chunks
    sample_chunks = chunks[:20] if len(chunks) > 20 else chunks
    kb_summary = "\n---\n".join(sample_chunks)

    if category == "edge":
        system_prompt = (
            "You are an expert QA test designer. Given excerpts from a knowledge base, "
            "generate challenging edge-case questions that test the limits of the system. "
            "These include: ambiguous questions, questions with multiple valid interpretations, "
            "questions that combine topics in unusual ways, hypothetical scenarios, "
            "negation questions, questions about exceptions to rules, and boundary conditions. "
            "Each question should still be related to the knowledge base content but approach it "
            "from an unusual angle."
        )
    elif category == "out_of_knowledge_base":
        system_prompt = (
            "You are an expert QA test designer. Given excerpts from a knowledge base, "
            "generate plausible questions that are OUTSIDE the scope of this knowledge base. "
            "These questions should be realistic (something a user might actually ask) "
            "but about topics NOT covered in the provided documents. "
            "The reference answer for each should explain that the information is not available "
            "in the knowledge base."
        )
    else:
        system_prompt = (
            "You are an expert QA test designer. Given excerpts from a knowledge base, "
            "generate common, expected questions that a typical user would ask in normal scenarios."
        )

    user_prompt = (
        f"Knowledge base excerpts:\n\n{kb_summary}\n\n"
        f"Generate exactly {count} questions as a JSON array. "
        f"Each element must have: "
        f'"question" (the question text) and "reference_answer" (the expected answer). '
        f"Return ONLY the JSON array, no other text."
    )

    try:
        response = client.chat.completions.create(
            model=DEFAULT_EVAL_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=TESTGEN_QUESTION_TEMPERATURE,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "[]"
        parsed = _json.loads(raw)
        # Handle both {"questions": [...]} and [...] formats
        if isinstance(parsed, dict):
            items = parsed.get("questions", parsed.get("items", []))
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = []

        results = []
        for item in items[:count]:
            results.append({
                "user_input": item.get("question", ""),
                "reference": item.get("reference_answer", ""),
                "reference_contexts": [],
                "synthesizer_name": category,
            })
        return results
    except Exception:
        logger.exception("Failed to generate %s questions via LLM", category)
        return []


# ---------------------------------------------------------------------------
# Graph RAG question generators
# ---------------------------------------------------------------------------

def _get_kg_graph(kg: KnowledgeGraph):
    """Build a NetworkX graph from the KG's entity_overlap and summary_similarity relationships.

    Returns (G, node_lookup) where G is an undirected graph with node IDs as keys
    and node_lookup maps str(node.id) → node object.
    """
    import networkx as nx

    G = nx.Graph()
    node_lookup: dict[str, object] = {}
    for node in kg.nodes:
        nid = str(node.id)
        G.add_node(nid)
        node_lookup[nid] = node

    for rel in kg.relationships:
        if rel.type in ("entity_overlap", "summary_similarity"):
            src_id = str(rel.source.id)
            tgt_id = str(rel.target.id)
            if src_id in node_lookup and tgt_id in node_lookup:
                score = rel.properties.get(rel.type, 0.5)
                if isinstance(score, (int, float)):
                    G.add_edge(src_id, tgt_id, weight=float(score))

    return G, node_lookup


def _generate_bridge_questions(
    kg: KnowledgeGraph,
    count: int,
    llm_client,
) -> list[dict]:
    """Generate questions that require connecting two distant KG nodes (path distance ≥ 3).

    These test whether the external model can reason across multiple document sections.
    """
    if count <= 0:
        return []

    import networkx as nx
    import random

    G, node_lookup = _get_kg_graph(kg)
    if len(G.nodes) < 4:
        logger.warning("Not enough KG nodes for bridge questions (need ≥ 4, have %d)", len(G.nodes))
        return []

    # Collect candidate pairs from same connected component with distance ≥ 3
    candidate_pairs: list[tuple[str, str, list[str]]] = []
    for component in nx.connected_components(G):
        if len(component) < 4:
            continue
        nodes_list = list(component)
        # Sample pairs to avoid O(n^2) on large graphs
        sample_size = min(len(nodes_list), 30)
        sampled = random.sample(nodes_list, sample_size)
        for i in range(len(sampled)):
            for j in range(i + 1, len(sampled)):
                try:
                    dist = nx.shortest_path_length(G, sampled[i], sampled[j])
                    if dist >= 3:
                        path = nx.shortest_path(G, sampled[i], sampled[j])
                        candidate_pairs.append((sampled[i], sampled[j], path))
                except nx.NetworkXNoPath:
                    pass

    if not candidate_pairs:
        logger.info("No node pairs with distance ≥ 3 found for bridge questions")
        return []

    # Shuffle and take what we need (with overgeneration buffer)
    random.shuffle(candidate_pairs)
    selected_pairs = candidate_pairs[: count * 2]

    results = []
    for src_id, tgt_id, path in selected_pairs:
        if len(results) >= count:
            break
        src_node = node_lookup[src_id]
        tgt_node = node_lookup[tgt_id]
        src_summary = src_node.properties.get("summary", src_node.properties.get("page_content", ""))[:500]
        tgt_summary = tgt_node.properties.get("summary", tgt_node.properties.get("page_content", ""))[:500]
        src_entities = src_node.properties.get("entities", [])
        tgt_entities = tgt_node.properties.get("entities", [])

        # Build human-readable path label using entities at each hop
        path_labels: list[str] = []
        for nid in path:
            n = node_lookup.get(nid)
            if n:
                ents = n.properties.get("entities", [])
                label = ents[0] if ents else (n.properties.get("summary", "")[:30] + "...")
                path_labels.append(label)

        system_prompt = (
            "You are an expert QA test designer specialising in multi-hop reasoning. "
            "Given two excerpts from different parts of a document that are indirectly related, "
            "generate ONE question that requires connecting them through intermediate reasoning. "
            "Also provide a reference answer that clearly explains the connection. "
            "Return a JSON object with keys: question, reference_answer."
        )
        user_prompt = (
            f"Excerpt A:\n{src_summary}\n\n"
            f"Excerpt B:\n{tgt_summary}\n\n"
            f"Key entities in A: {src_entities[:5]}\n"
            f"Key entities in B: {tgt_entities[:5]}\n\n"
            "Generate a bridge question connecting these two excerpts. "
            "Return ONLY the JSON object."
        )
        try:
            response = llm_client.chat.completions.create(
                model=DEFAULT_EVAL_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=TESTGEN_QUESTION_TEMPERATURE,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            raw = _json.loads(response.choices[0].message.content or "{}")
            question = raw.get("question", "").strip()
            reference_answer = raw.get("reference_answer", "").strip()
            if question and reference_answer:
                results.append({
                    "user_input": question,
                    "reference": reference_answer,
                    "reference_contexts": [src_summary, tgt_summary],
                    "synthesizer_name": "bridge",
                    "metadata": {
                        "graph_path": path_labels,
                        "difficulty": "hard",
                    },
                })
        except Exception:
            logger.exception("Failed to generate bridge question for node pair")

    return results


def _generate_comparative_questions(
    kg: KnowledgeGraph,
    count: int,
    llm_client,
) -> list[dict]:
    """Generate compare-and-contrast questions for directly related node pairs (entity_overlap edges)."""
    if count <= 0:
        return []

    import random

    # Find all entity_overlap relationships
    overlap_pairs: list[tuple[object, object]] = []
    for rel in kg.relationships:
        if rel.type == "entity_overlap":
            overlap_pairs.append((rel.source, rel.target))

    if not overlap_pairs:
        logger.info("No entity_overlap relationships found for comparative questions")
        return []

    random.shuffle(overlap_pairs)
    selected_pairs = overlap_pairs[: count * 2]

    results = []
    for src_node, tgt_node in selected_pairs:
        if len(results) >= count:
            break
        src_summary = src_node.properties.get("summary", src_node.properties.get("page_content", ""))[:500]
        tgt_summary = tgt_node.properties.get("summary", tgt_node.properties.get("page_content", ""))[:500]
        src_entities = src_node.properties.get("entities", [])
        tgt_entities = tgt_node.properties.get("entities", [])
        shared = list(set(src_entities) & set(tgt_entities))[:5]

        system_prompt = (
            "You are an expert QA test designer. "
            "Given two related excerpts from the same document, generate ONE comparison question "
            "that asks about the similarities or differences between them. "
            "The reference answer should highlight key similarities and differences. "
            "Return a JSON object with keys: question, reference_answer."
        )
        user_prompt = (
            f"Excerpt A:\n{src_summary}\n\n"
            f"Excerpt B:\n{tgt_summary}\n\n"
            f"Shared concepts: {shared}\n\n"
            "Generate a comparison question. Return ONLY the JSON object."
        )
        try:
            response = llm_client.chat.completions.create(
                model=DEFAULT_EVAL_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=TESTGEN_QUESTION_TEMPERATURE,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            raw = _json.loads(response.choices[0].message.content or "{}")
            question = raw.get("question", "").strip()
            reference_answer = raw.get("reference_answer", "").strip()
            if question and reference_answer:
                a_snippet = src_summary[:40].replace("\n", " ") + "..."
                b_snippet = tgt_summary[:40].replace("\n", " ") + "..."
                results.append({
                    "user_input": question,
                    "reference": reference_answer,
                    "reference_contexts": [src_summary, tgt_summary],
                    "synthesizer_name": "comparative",
                    "metadata": {
                        "graph_path": [a_snippet, "↔", b_snippet],
                        "difficulty": "medium",
                    },
                })
        except Exception:
            logger.exception("Failed to generate comparative question")

    return results


def _generate_community_questions(
    kg: KnowledgeGraph,
    count: int,
    llm_client,
) -> list[dict]:
    """Generate high-level thematic questions by grouping KG nodes by theme."""
    if count <= 0:
        return []

    import random

    # Group nodes by their first theme (already extracted in KG build step 8)
    theme_groups: dict[str, list[object]] = {}
    for node in kg.nodes:
        themes = node.properties.get("themes", [])
        if not themes:
            continue
        theme = themes[0] if isinstance(themes[0], str) else str(themes[0])
        theme = theme.strip()
        if theme:
            theme_groups.setdefault(theme, []).append(node)

    if not theme_groups:
        logger.info("No themes found in KG nodes for community questions")
        return []

    # Sort themes by cluster size descending; take top clusters
    sorted_themes = sorted(theme_groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_themes = sorted_themes[:max(count, 5)]

    results = []
    per_theme = max(1, count // len(top_themes))
    remainder = count - per_theme * len(top_themes)

    for idx, (theme, nodes) in enumerate(top_themes):
        if len(results) >= count:
            break
        theme_count = per_theme + (1 if idx < remainder else 0)
        # Concatenate summaries from up to 5 representative nodes
        sample_nodes = random.sample(nodes, min(5, len(nodes)))
        context_parts = []
        for n in sample_nodes:
            s = n.properties.get("summary", n.properties.get("page_content", ""))[:300]
            if s:
                context_parts.append(s)
        context = "\n---\n".join(context_parts)

        system_prompt = (
            "You are an expert QA test designer. "
            "Given several excerpts that all relate to a common theme, generate high-level questions "
            "that test comprehensive understanding of the topic. "
            "Each question should require synthesising information across the excerpts. "
            f"Generate exactly {theme_count} questions as a JSON array. "
            "Each element must have: question, reference_answer. "
            "Return ONLY the JSON array."
        )
        user_prompt = (
            f"Theme: {theme}\n\n"
            f"Related excerpts:\n{context}\n\n"
            f"Generate {theme_count} community-level question(s) about this theme."
        )
        try:
            response = llm_client.chat.completions.create(
                model=DEFAULT_EVAL_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=TESTGEN_QUESTION_TEMPERATURE,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            raw = _json.loads(response.choices[0].message.content or "[]")
            if isinstance(raw, dict):
                items = raw.get("questions", raw.get("items", []))
            elif isinstance(raw, list):
                items = raw
            else:
                items = []
            for item in items[:theme_count]:
                question = item.get("question", "").strip()
                reference_answer = item.get("reference_answer", "").strip()
                if question and reference_answer:
                    results.append({
                        "user_input": question,
                        "reference": reference_answer,
                        "reference_contexts": context_parts,
                        "synthesizer_name": "community",
                        "metadata": {
                            "graph_path": [f"theme:{theme}"],
                            "difficulty": "easy",
                        },
                    })
        except Exception:
            logger.exception("Failed to generate community questions for theme '%s'", theme)

    return results[:count]


# Difficulty mapping for ALL question types
_DIFFICULTY_MAP: dict[str, str] = {
    # Easy
    "single_hop_specific": "easy",
    "community": "easy",
    "out_of_knowledge_base": "easy",
    # Medium
    "typical": "medium",
    "in_knowledge_base": "medium",
    "multi_hop_specific": "medium",
    "comparative": "medium",
    # Hard
    "multi_hop_abstract": "hard",
    "bridge": "hard",
    "edge": "hard",
}


def _assign_difficulty(questions: list[dict]) -> None:
    """Tag every question in-place with a difficulty level in metadata."""
    for q in questions:
        synth = q.get("synthesizer_name") or q.get("category") or ""
        difficulty = _DIFFICULTY_MAP.get(synth, "medium")
        meta = q.get("metadata")
        if meta is None:
            q["metadata"] = {"difficulty": difficulty}
        elif "difficulty" not in meta:
            meta["difficulty"] = difficulty


def generate_project_testset(
    chunks: list[str],
    testset_size: int = 10,
    use_personas: bool = True,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
    num_workers: int = 4,
    question_categories: dict[str, int] | None = None,
    project_id: int | None = None,
    graph_rag_kg_source: str = "chunks",
    node_sample_size: int = 0,
    fast_mode: bool = False,
) -> dict:
    """Unified entry point for project-scoped test set generation.

    Routes to persona-based or chunk-based generation and returns
    a normalized dict with 'personas' and 'questions' keys.

    question_categories: optional dict mapping category names to percentages.
    Supported categories: typical, in_knowledge_base, edge, out_of_knowledge_base,
    bridge, comparative, community (last three require a built KG).
    When provided, questions are generated per-category and tagged.

    graph_rag_kg_source: "chunks" (default) or "documents". Controls which KG is
    used for Graph RAG question types (bridge, comparative, community).
    """
    # Initialize progress tracking
    if project_id is not None:
        set_progress(project_id, {
            "stage": "building_knowledge_graph",
            "questions_generated": 0,
            "target_size": testset_size,
        }, kg_source="testset")

    try:
        return _generate_project_testset_inner(
            chunks=chunks,
            testset_size=testset_size,
            use_personas=use_personas,
            num_personas=num_personas,
            custom_personas=custom_personas,
            query_distribution=query_distribution,
            num_workers=num_workers,
            question_categories=question_categories,
            project_id=project_id,
            graph_rag_kg_source=graph_rag_kg_source,
            node_sample_size=node_sample_size,
            fast_mode=fast_mode,
        )
    finally:
        if project_id is not None:
            clear_progress(project_id, kg_source="testset")


def _generate_project_testset_inner(
    chunks: list[str],
    testset_size: int = 10,
    use_personas: bool = True,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
    num_workers: int = 4,
    question_categories: dict[str, int] | None = None,
    project_id: int | None = None,
    graph_rag_kg_source: str = "chunks",
    node_sample_size: int = 0,
    fast_mode: bool = False,
) -> dict:
    # ---------------------------------------------------------------------------
    # Resolve effective chunks and prebuilt KG for KG-node sampling.
    #
    # When node_sample_size > 0 and a complete KG already exists for this
    # project we sample nodes directly from the stored KG instead of
    # rebuilding it from a random subset of chunks.  This is much faster
    # because the full 11-step transform pipeline is skipped entirely.
    #
    # For Graph RAG categories (bridge/comparative/community) we always use
    # the full chunk list because those questions rely on graph-wide
    # connectivity — sampling would degrade quality.
    # ---------------------------------------------------------------------------
    prebuilt_kg: "KnowledgeGraph | None" = None
    effective_chunks = chunks

    if node_sample_size > 0:
        if project_id is not None:
            kg_json = load_full_kg_json(project_id, kg_source=graph_rag_kg_source)
            if kg_json is not None:
                import json as _json
                num_nodes = len(_json.loads(kg_json).get("nodes", []))
                sample_n = min(node_sample_size, num_nodes)
                logger.info(
                    "project %d: sampling %d/%d KG nodes — skipping KG rebuild",
                    project_id, sample_n, num_nodes,
                )
                prebuilt_kg, effective_chunks = sample_kg_from_json(kg_json, sample_n)
                if project_id is not None:
                    update_progress(project_id, kg_source="testset", stage="kg_loaded_from_cache")
            else:
                # No complete KG available — fall back to sampling chunks directly
                if node_sample_size < len(chunks):
                    logger.info(
                        "project %d: no complete KG found — sampling %d/%d chunks",
                        project_id, node_sample_size, len(chunks),
                    )
                    effective_chunks = random.sample(chunks, node_sample_size)
        elif node_sample_size < len(chunks):
            effective_chunks = random.sample(chunks, node_sample_size)

    # If no categories specified, generate all as "in_knowledge_base" (legacy behavior)
    if not question_categories:
        if use_personas:
            result = generate_testset_with_personas(
                chunks=effective_chunks,
                testset_size=testset_size,
                num_personas=num_personas,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
                project_id=project_id,
                prebuilt_kg=prebuilt_kg,
                fast_mode=fast_mode,
            )
        else:
            questions = generate_testset_from_chunks(
                chunks=effective_chunks,
                testset_size=testset_size,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
                project_id=project_id,
            )
            result = {"personas": [], "questions": questions}
        # Tag all questions as in_knowledge_base for consistency
        for q in result.get("questions", []):
            q["category"] = "in_knowledge_base"
        _assign_difficulty(result.get("questions", []))
        return result

    # Category-based generation: split testset_size by category percentages
    total_pct = sum(question_categories.values())
    if total_pct == 0:
        return {"personas": [], "questions": []}

    all_questions: list[dict] = []
    all_personas: list[dict] = []

    # Bucket categories by generation method
    ragas_categories = {}
    llm_categories = {}
    graph_rag_categories = {}
    for cat, pct in question_categories.items():
        if pct <= 0:
            continue
        if cat in ("typical", "in_knowledge_base"):
            ragas_categories[cat] = pct
        elif cat in ("edge", "out_of_knowledge_base"):
            llm_categories[cat] = pct
        elif cat in ("bridge", "comparative", "community"):
            graph_rag_categories[cat] = pct

    # Generate Ragas-based questions (typical + in_knowledge_base combined)
    ragas_total_pct = sum(ragas_categories.values())
    if ragas_total_pct > 0:
        ragas_count = max(1, round(testset_size * ragas_total_pct / total_pct))

        if use_personas:
            ragas_result = generate_testset_with_personas(
                chunks=effective_chunks,
                testset_size=ragas_count,
                num_personas=num_personas,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
                project_id=project_id,
                prebuilt_kg=prebuilt_kg,
                fast_mode=fast_mode,
            )
            all_personas = ragas_result.get("personas", [])
            ragas_questions = ragas_result.get("questions", [])
        else:
            ragas_questions = generate_testset_from_chunks(
                chunks=effective_chunks,
                testset_size=ragas_count,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
                project_id=project_id,
            )

        # Split ragas questions between typical and in_knowledge_base
        if "typical" in ragas_categories and "in_knowledge_base" in ragas_categories:
            typical_share = ragas_categories["typical"] / ragas_total_pct
            typical_count = round(len(ragas_questions) * typical_share)
            for i, q in enumerate(ragas_questions):
                q["category"] = "typical" if i < typical_count else "in_knowledge_base"
        else:
            cat_name = next(iter(ragas_categories))
            for q in ragas_questions:
                q["category"] = cat_name

        all_questions.extend(ragas_questions)

    # Generate LLM-based questions (edge + out_of_knowledge_base)
    if project_id is not None and llm_categories:
        update_progress(project_id, kg_source="testset", stage="generating_special_categories")
    for cat, pct in llm_categories.items():
        cat_count = max(1, round(testset_size * pct / total_pct))
        cat_questions = _generate_category_questions_via_llm(effective_chunks, cat, cat_count)
        for q in cat_questions:
            q["category"] = cat
        all_questions.extend(cat_questions)
        if project_id is not None:
            increment_questions(project_id, len(cat_questions))

    # Generate Graph RAG questions (bridge, comparative, community)
    if graph_rag_categories:
        # Determine source texts and cache key based on selected KG source
        if graph_rag_kg_source == "documents" and project_id is not None:
            source_texts = _fetch_document_texts(project_id)
            kg_source_key = "documents"
        else:
            source_texts = chunks
            kg_source_key = "chunks"

        # Load the KG from cache or build fresh
        kg_for_graph: KnowledgeGraph | None = None
        if project_id is not None:
            cached = load_cached_kg(project_id, source_texts, allow_partial=False, kg_source=kg_source_key)
            if cached is not None:
                kg_for_graph = cached  # type: ignore[assignment]

        if kg_for_graph is None:
            if project_id is not None:
                update_progress(project_id, kg_source="testset", stage="building_knowledge_graph")
            llm, embeddings, _ = _build_llm_and_embeddings()
            kg_for_graph = build_knowledge_graph(
                source_texts, llm=llm, embeddings=embeddings,
                project_id=project_id, kg_source=kg_source_key
            )

        _, _, llm_client = _build_llm_and_embeddings()

        _graph_generators = {
            "bridge": _generate_bridge_questions,
            "comparative": _generate_comparative_questions,
            "community": _generate_community_questions,
        }
        _stage_names = {
            "bridge": "generating_bridge_questions",
            "comparative": "generating_comparative_questions",
            "community": "generating_community_questions",
        }

        for cat, pct in graph_rag_categories.items():
            cat_count = max(1, round(testset_size * pct / total_pct))
            if project_id is not None:
                update_progress(project_id, kg_source="testset", stage=_stage_names[cat])
            generator = _graph_generators[cat]
            cat_questions = generator(kg_for_graph, cat_count, llm_client)
            for q in cat_questions:
                q["category"] = cat
            all_questions.extend(cat_questions)
            if project_id is not None:
                increment_questions(project_id, len(cat_questions))

    # Tag all questions with difficulty (covers all types)
    _assign_difficulty(all_questions)

    return {"personas": all_personas, "questions": all_questions}
