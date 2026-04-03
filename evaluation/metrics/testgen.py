"""Test question generation using Ragas testset generators.

Supports:
- Auto-generating personas from documents
- Single-hop questions (fact lookup from one chunk)
- Multi-hop questions (reasoning across multiple chunks)
- Pre-chunked data input
- Custom persona definitions
- Custom query distribution (single-hop / multi-hop mix)
"""

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


SYNTHESIZER_MAP = {
    "single_hop_specific": SingleHopSpecificQuerySynthesizer,
    "multi_hop_abstract": MultiHopAbstractQuerySynthesizer,
    "multi_hop_specific": MultiHopSpecificQuerySynthesizer,
}


def build_query_distribution(dist_config: dict[str, float], llm=None):
    """Build a Ragas QueryDistribution from a {name: weight} dict.

    Example input: {"single_hop_specific": 0.5, "multi_hop_abstract": 0.25, "multi_hop_specific": 0.25}
    """
    distribution = []
    for name, weight in dist_config.items():
        cls = SYNTHESIZER_MAP.get(name)
        if cls is None:
            raise ValueError(f"Unknown query type: {name}. Valid types: {list(SYNTHESIZER_MAP.keys())}")
        distribution.append((cls(llm=llm), weight))
    return distribution


def _build_llm_and_embeddings():
    client = OpenAI()
    llm = llm_factory("gpt-4o-mini", client=client, max_tokens=16384)
    embeddings = embedding_factory("openai", model="text-embedding-3-small", client=client)
    return llm, embeddings, client


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


def generate_testset_from_chunks(
    chunks: list[str],
    testset_size: int = 10,
    personas: list[Persona] | None = None,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
) -> list[dict]:
    """Generate test questions from pre-chunked text.

    Returns a list of dicts with 'user_input' (question) and 'reference' (expected answer).
    """
    llm, embeddings, client = _build_llm_and_embeddings()

    generator = TestsetGenerator(
        llm=llm,
        embedding_model=embeddings,
    )

    if personas is None:
        if custom_personas:
            personas = [
                Persona(name=p["name"], role_description=p["role_description"])
                for p in custom_personas
            ]

    qd = build_query_distribution(query_distribution, llm=llm) if query_distribution else None

    testset = generator.generate_with_chunks(
        chunks=chunks,
        testset_size=testset_size,
        query_distribution=qd,
    )

    df = testset.to_pandas()
    results = []
    for _, row in df.iterrows():
        results.append({
            "user_input": row.get("user_input", ""),
            "reference": row.get("reference", ""),
            "reference_contexts": row.get("reference_contexts", []),
            "synthesizer_name": row.get("synthesizer_name", ""),
        })
    return results


def generate_testset_with_personas(
    chunks: list[str],
    testset_size: int = 10,
    num_personas: int = 3,
    custom_personas: list[dict] | None = None,
    query_distribution: dict[str, float] | None = None,
) -> dict:
    """Generate test questions with persona information.

    Returns dict with 'personas' and 'questions' keys.
    """
    llm, embeddings, _ = _build_llm_and_embeddings()

    kg = build_knowledge_graph(chunks, llm=llm, embeddings=embeddings)

    if custom_personas:
        personas = [
            Persona(name=p["name"], role_description=p["role_description"])
            for p in custom_personas
        ]
    else:
        personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=num_personas)

    generator = TestsetGenerator(
        knowledge_graph=kg,
        persona_list=personas,
        llm=llm,
    )

    qd = build_query_distribution(query_distribution, llm=llm) if query_distribution else None

    testset = generator.generate(testset_size=testset_size, query_distribution=qd)

    df = testset.to_pandas()
    questions = []
    for _, row in df.iterrows():
        questions.append({
            "user_input": row.get("user_input", ""),
            "reference": row.get("reference", ""),
            "reference_contexts": row.get("reference_contexts", []),
            "synthesizer_name": row.get("synthesizer_name", ""),
        })

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
        )
    else:
        questions = generate_testset_from_chunks(
            chunks=chunks,
            testset_size=testset_size,
            custom_personas=custom_personas,
            query_distribution=query_distribution,
        )
        return {"personas": [], "questions": questions}
