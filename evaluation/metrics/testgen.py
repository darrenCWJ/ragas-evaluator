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
import signal
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from openai import OpenAI
from ragas.llms import llm_factory
from ragas.embeddings import embedding_factory
from ragas.testset import TestsetGenerator
from ragas.testset.persona import Persona, generate_personas_from_kg
from ragas.testset.graph import KnowledgeGraph, Node, NodeType
from ragas.testset.transforms import (
    apply_transforms,
    HeadlinesExtractor,
    HeadlineSplitter,
    KeyphrasesExtractor,
    OverlapScoreBuilder,
)
from ragas.testset.synthesizers.single_hop.specific import SingleHopSpecificQuerySynthesizer
from ragas.testset.synthesizers.multi_hop import (
    MultiHopAbstractQuerySynthesizer,
    MultiHopSpecificQuerySynthesizer,
)

from db.init import get_db


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
# Progress tracking — in-memory, keyed by project_id
# ---------------------------------------------------------------------------

_progress_lock = threading.Lock()
_progress: dict[int, dict] = {}


def set_progress(project_id: int, data: dict) -> None:
    with _progress_lock:
        _progress[project_id] = data


def update_progress(project_id: int, **fields) -> None:
    with _progress_lock:
        if project_id in _progress:
            _progress[project_id].update(fields)


def get_progress(project_id: int) -> dict | None:
    with _progress_lock:
        entry = _progress.get(project_id)
        return entry.copy() if entry is not None else None


def clear_progress(project_id: int) -> None:
    with _progress_lock:
        _progress.pop(project_id, None)


def increment_questions(project_id: int, count: int = 1) -> None:
    with _progress_lock:
        if project_id in _progress:
            _progress[project_id]["questions_generated"] = (
                _progress[project_id].get("questions_generated", 0) + count
            )


# Over-generate per worker, then deduplicate and trim to requested size.
OVERGENERATE_FACTOR = 1.3
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


def _build_llm_and_embeddings():
    client = OpenAI()
    llm = llm_factory("gpt-4o-mini", client=client, max_tokens=16384)
    embeddings = embedding_factory(
        "openai", model="text-embedding-3-small", client=client
    )
    return llm, embeddings, client


# ---------------------------------------------------------------------------
# Knowledge-graph helpers
# ---------------------------------------------------------------------------

def _chunks_hash(chunks: list[str]) -> str:
    """Return a stable hash of chunk contents for cache invalidation."""
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk.encode("utf-8"))
    return h.hexdigest()[:16]


def load_cached_kg(project_id: int, chunks: list[str]) -> KnowledgeGraph | None:
    """Return a cached *complete* KG from the database if one exists.

    Partial KGs (from interrupted builds) are ignored — they will be
    replaced by a fresh build.
    """
    h = _chunks_hash(chunks)
    db = get_db()
    row = db.execute(
        "SELECT kg_json, is_complete FROM knowledge_graphs "
        "WHERE project_id = ? AND chunks_hash = ?",
        (project_id, h),
    ).fetchone()
    if row is None:
        return None
    if not row["is_complete"]:
        logger.info(
            "Found partial KG cache for project %d — will rebuild", project_id
        )
        return None

    logger.info("Loading cached knowledge graph for project %d from DB", project_id)
    # KnowledgeGraph.load expects a file path — write to a temp file.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(row["kg_json"])
        tmp_path = f.name
    try:
        kg = KnowledgeGraph.load(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return kg


def save_kg_to_db(
    kg: KnowledgeGraph,
    project_id: int,
    chunks: list[str],
    *,
    is_complete: bool = True,
    completed_steps: int = 4,
    total_steps: int = 4,
) -> None:
    """Persist a KG to the database, replacing any stale entry for this project."""
    h = _chunks_hash(chunks)
    # Serialize KG via its save method to get the JSON string.
    with tempfile.NamedTemporaryFile(mode="r", suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        kg.save(tmp_path)
        kg_json = Path(tmp_path).read_text(encoding="utf-8")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    db = get_db()
    # Remove old entries for this project (documents may have changed).
    db.execute("DELETE FROM knowledge_graphs WHERE project_id = ?", (project_id,))
    db.execute(
        "INSERT INTO knowledge_graphs "
        "(project_id, chunks_hash, kg_json, num_nodes, num_chunks, is_complete, completed_steps, total_steps) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, h, kg_json, len(kg.nodes), len(chunks), is_complete, completed_steps, total_steps),
    )
    db.commit()
    status = "complete" if is_complete else f"partial ({completed_steps}/{total_steps})"
    logger.info("Saved %s KG for project %d to DB (%d nodes)", status, project_id, len(kg.nodes))


def delete_kg_from_db(project_id: int) -> bool:
    """Delete the cached KG for a project. Returns True if a row was deleted."""
    db = get_db()
    cursor = db.execute("DELETE FROM knowledge_graphs WHERE project_id = ?", (project_id,))
    db.commit()
    return cursor.rowcount > 0


def get_kg_info(project_id: int) -> dict | None:
    """Return metadata about the cached KG for a project (without the full JSON)."""
    db = get_db()
    row = db.execute(
        "SELECT id, project_id, chunks_hash, num_nodes, num_chunks, "
        "is_complete, completed_steps, total_steps, created_at "
        "FROM knowledge_graphs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def build_knowledge_graph(
    chunks: list[str],
    llm=None,
    embeddings=None,
    project_id: int | None = None,
) -> KnowledgeGraph:
    """Build a KnowledgeGraph from text chunks and apply transforms.

    When *project_id* is provided the KG is cached in the database. Subsequent
    calls with the same project and chunk content return the cached version
    instantly.
    """
    if project_id is not None:
        cached = load_cached_kg(project_id, chunks)
        if cached is not None:
            update_progress(project_id, stage="kg_loaded_from_cache")
            return cached

    if llm is None or embeddings is None:
        llm, embeddings, _ = _build_llm_and_embeddings()

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
    # If a transform fails (e.g. rate limit), save the partial KG so
    # progress isn't lost — later calls can resume from the cache.
    transform_steps = [
        ("kg_extracting_headlines", HeadlinesExtractor(llm=llm)),
        ("kg_splitting_headlines", HeadlineSplitter(min_tokens=100, max_tokens=500)),
        ("kg_extracting_keyphrases", KeyphrasesExtractor(llm=llm, property_name="keyphrases", max_num=10)),
        ("kg_building_overlap", OverlapScoreBuilder(
            property_name="keyphrases",
            new_property_name="overlap_score",
            threshold=0.01,
            distance_threshold=0.9,
        )),
    ]
    completed_steps = 0
    for stage_name, transform in transform_steps:
        if project_id is not None:
            update_progress(project_id, stage=stage_name)
        logger.info("KG transform: %s (%d nodes)", stage_name, len(kg.nodes))
        try:
            apply_transforms(kg, transforms=[transform])
            completed_steps += 1
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
                )
            raise

    if project_id is not None:
        save_kg_to_db(kg, project_id, chunks)

    return kg


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
    MAX_CHARS_PER_BATCH = 80_000
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
            model="gpt-4o-mini",
            temperature=0,
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
        model="gpt-4o-mini",
        temperature=0.7,
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
) -> list[Persona]:
    """Generate personas from document chunks, or use custom-defined ones."""
    if custom_personas:
        return [_merge_persona_fields(p) for p in custom_personas]

    if fast:
        raw = generate_personas_fast(chunks, num_personas=num_personas)
        return [_merge_persona_fields(p) for p in raw]

    llm, embeddings, _ = _build_llm_and_embeddings()
    kg = build_knowledge_graph(chunks, llm=llm, embeddings=embeddings)
    personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=num_personas)
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
    llm, _, _ = _build_llm_and_embeddings()
    generator = TestsetGenerator(
        knowledge_graph=kg,
        persona_list=personas,
        llm=llm,
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
            if _shutdown_event.is_set():
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
) -> dict:
    """Generate test questions with persona information using parallel workers.

    The knowledge graph is built once (sequential), then generation is split
    across *num_workers* threads sharing the same KG and persona list.
    """
    llm, embeddings, _ = _build_llm_and_embeddings()

    logger.info("Building knowledge graph from %d chunks...", len(chunks))
    if project_id is not None:
        update_progress(project_id, stage="building_knowledge_graph")
    kg = build_knowledge_graph(chunks, llm=llm, embeddings=embeddings, project_id=project_id)

    if project_id is not None:
        update_progress(project_id, stage="generating_personas")

    if custom_personas:
        personas = [_merge_persona_fields(p) for p in custom_personas]
    else:
        personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=num_personas)

    if project_id is not None:
        update_progress(project_id, stage="generating_questions")

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
                if _shutdown_event.is_set():
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
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
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
) -> dict:
    """Unified entry point for project-scoped test set generation.

    Routes to persona-based or chunk-based generation and returns
    a normalized dict with 'personas' and 'questions' keys.

    question_categories: optional dict mapping category names to percentages.
    Supported categories: typical, in_knowledge_base, edge, out_of_knowledge_base.
    When provided, questions are generated per-category and tagged.
    """
    # Initialize progress tracking
    if project_id is not None:
        set_progress(project_id, {
            "stage": "building_knowledge_graph",
            "questions_generated": 0,
            "target_size": testset_size,
        })

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
        )
    finally:
        if project_id is not None:
            clear_progress(project_id)


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
) -> dict:
    # If no categories specified, generate all as "in_knowledge_base" (legacy behavior)
    if not question_categories:
        if use_personas:
            result = generate_testset_with_personas(
                chunks=chunks,
                testset_size=testset_size,
                num_personas=num_personas,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
                project_id=project_id,
            )
        else:
            questions = generate_testset_from_chunks(
                chunks=chunks,
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
        return result

    # Category-based generation: split testset_size by category percentages
    total_pct = sum(question_categories.values())
    if total_pct == 0:
        return {"personas": [], "questions": []}

    all_questions: list[dict] = []
    all_personas: list[dict] = []

    # Ragas-based categories (typical + in_knowledge_base) use the existing generators
    ragas_categories = {}
    llm_categories = {}
    for cat, pct in question_categories.items():
        if pct <= 0:
            continue
        if cat in ("typical", "in_knowledge_base"):
            ragas_categories[cat] = pct
        elif cat in ("edge", "out_of_knowledge_base"):
            llm_categories[cat] = pct

    # Generate Ragas-based questions (typical + in_knowledge_base combined)
    ragas_total_pct = sum(ragas_categories.values())
    if ragas_total_pct > 0:
        ragas_count = max(1, round(testset_size * ragas_total_pct / total_pct))

        if use_personas:
            ragas_result = generate_testset_with_personas(
                chunks=chunks,
                testset_size=ragas_count,
                num_personas=num_personas,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
                project_id=project_id,
            )
            all_personas = ragas_result.get("personas", [])
            ragas_questions = ragas_result.get("questions", [])
        else:
            ragas_questions = generate_testset_from_chunks(
                chunks=chunks,
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
        update_progress(project_id, stage="generating_special_categories")
    for cat, pct in llm_categories.items():
        cat_count = max(1, round(testset_size * pct / total_pct))
        cat_questions = _generate_category_questions_via_llm(chunks, cat, cat_count)
        for q in cat_questions:
            q["category"] = cat
        all_questions.extend(cat_questions)
        if project_id is not None:
            increment_questions(project_id, len(cat_questions))

    return {"personas": all_personas, "questions": all_questions}
