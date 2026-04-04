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

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

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


logger = logging.getLogger(__name__)

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


def build_knowledge_graph(chunks: list[str], llm=None, embeddings=None):
    """Build a KnowledgeGraph from text chunks and apply transforms."""
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

    transforms = [
        HeadlinesExtractor(llm=llm),
        HeadlineSplitter(min_tokens=100, max_tokens=500),
        KeyphrasesExtractor(llm=llm, property_name="keyphrases", max_num=10),
        OverlapScoreBuilder(
            property_name="keyphrases",
            new_property_name="overlap_score",
            threshold=0.01,
            distance_threshold=0.9,
        ),
    ]
    apply_transforms(kg, transforms=transforms)
    return kg


def generate_personas(
    chunks: list[str],
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
) -> list[Persona]:
    """Generate personas from document chunks, or use custom-defined ones."""
    if custom_personas:
        return [
            Persona(name=p["name"], role_description=p["role_description"])
            for p in custom_personas
        ]

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
    return [_row_to_dict(row) for _, row in testset.to_pandas().iterrows()]


def _worker_generate_from_kg(
    kg: KnowledgeGraph,
    personas: list[Persona],
    batch_size: int,
    query_distribution: dict[str, float] | None,
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
    return [_row_to_dict(row) for _, row in testset.to_pandas().iterrows()]


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
        results = _worker_generate_from_chunks(chunks, generate_size, query_distribution)
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

    all_questions: list[dict] = []
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = [
            pool.submit(
                _worker_generate_from_chunks,
                partition,
                per_worker,
                query_distribution,
            )
            for partition in chunk_partitions
        ]
        for future in as_completed(futures):
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
) -> dict:
    """Generate test questions with persona information using parallel workers.

    The knowledge graph is built once (sequential), then generation is split
    across *num_workers* threads sharing the same KG and persona list.
    """
    llm, embeddings, _ = _build_llm_and_embeddings()

    logger.info("Building knowledge graph from %d chunks...", len(chunks))
    kg = build_knowledge_graph(chunks, llm=llm, embeddings=embeddings)

    if custom_personas:
        personas = [
            Persona(name=p["name"], role_description=p["role_description"])
            for p in custom_personas
        ]
    else:
        personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=num_personas)

    effective_workers = max(1, min(num_workers, testset_size))

    if effective_workers <= 1:
        generate_size = int(testset_size * OVERGENERATE_FACTOR)
        questions = _worker_generate_from_kg(kg, personas, generate_size, query_distribution)
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

        all_questions: list[dict] = []
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = [
                pool.submit(
                    _worker_generate_from_kg,
                    kg,
                    personas,
                    per_worker,
                    query_distribution,
                )
                for _ in range(effective_workers)
            ]
            for future in as_completed(futures):
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


def generate_project_testset(
    chunks: list[str],
    testset_size: int = 10,
    use_personas: bool = True,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
    num_workers: int = 4,
) -> dict:
    """Unified entry point for project-scoped test set generation.

    Routes to persona-based or chunk-based generation and returns
    a normalized dict with 'personas' and 'questions' keys.
    """
    if use_personas:
        return generate_testset_with_personas(
            chunks=chunks,
            testset_size=testset_size,
            num_personas=num_personas,
            custom_personas=custom_personas,
            query_distribution=query_distribution,
            num_workers=num_workers,
        )
    else:
        questions = generate_testset_from_chunks(
            chunks=chunks,
            testset_size=testset_size,
            custom_personas=custom_personas,
            query_distribution=query_distribution,
            num_workers=num_workers,
        )
        return {"personas": [], "questions": questions}
