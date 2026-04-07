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
        import json as _json

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
) -> dict:
    """Unified entry point for project-scoped test set generation.

    Routes to persona-based or chunk-based generation and returns
    a normalized dict with 'personas' and 'questions' keys.

    question_categories: optional dict mapping category names to percentages.
    Supported categories: typical, in_knowledge_base, edge, out_of_knowledge_base.
    When provided, questions are generated per-category and tagged.
    """
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
            )
        else:
            questions = generate_testset_from_chunks(
                chunks=chunks,
                testset_size=testset_size,
                custom_personas=custom_personas,
                query_distribution=query_distribution,
                num_workers=num_workers,
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
    for cat, pct in llm_categories.items():
        cat_count = max(1, round(testset_size * pct / total_pct))
        cat_questions = _generate_category_questions_via_llm(chunks, cat, cat_count)
        for q in cat_questions:
            q["category"] = cat
        all_questions.extend(cat_questions)

    return {"personas": all_personas, "questions": all_questions}
