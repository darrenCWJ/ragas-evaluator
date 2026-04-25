"""Smoke tests — verify every third-party library and internal module can be imported.

These tests catch missing dependencies early (e.g. a package removed from
requirements.txt, a bad install, or a syntax error in a module) without
needing a running server or real API keys.
"""

import importlib

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import(module: str) -> None:
    """Assert that a module can be imported without errors."""
    importlib.import_module(module)


# ---------------------------------------------------------------------------
# Third-party libraries (from requirements.txt)
# ---------------------------------------------------------------------------

THIRD_PARTY_LIBS = [
    "openai",
    "ragas",
    "dotenv",
    "fastapi",
    "uvicorn",
    "aiofiles",
    "multipart",
    "pypdf",
    "docx",
    "chromadb",
    "sentence_transformers",
    "rank_bm25",
    "langchain_text_splitters",
    "tiktoken",
    "anthropic",
    "google.genai",
    "jsonpath_ng",
    "sacrebleu",
    "rouge_score",
    "networkx",
    "psycopg2",
    "rapidfuzz",
]


@pytest.mark.unit
@pytest.mark.parametrize("module", THIRD_PARTY_LIBS)
def test_third_party_library_importable(module: str) -> None:
    """Each required third-party library must be importable."""
    _import(module)


# ---------------------------------------------------------------------------
# Internal pipeline modules
# ---------------------------------------------------------------------------

PIPELINE_MODULES = [
    "pipeline.chunking",
    "pipeline.embedding",
    "pipeline.vectorstore",
    "pipeline.bm25",
    "pipeline.rag",
    "pipeline.llm",
    "pipeline.reranker",
]


@pytest.mark.unit
@pytest.mark.parametrize("module", PIPELINE_MODULES)
def test_pipeline_module_importable(module: str) -> None:
    """Each pipeline module must be importable."""
    _import(module)


# ---------------------------------------------------------------------------
# Evaluation metric modules
# ---------------------------------------------------------------------------

METRIC_MODULES = [
    "evaluation.metrics.answer_relevancy",
    "evaluation.metrics.answer_accuracy",
    "evaluation.metrics.agent_goal_accuracy",
    "evaluation.metrics.aspect_critic",
    "evaluation.metrics.bleu_score",
    "evaluation.metrics.chrf_score",
    "evaluation.metrics.context_entities_recall",
    "evaluation.metrics.context_precision",
    "evaluation.metrics.context_recall",
    "evaluation.metrics.context_relevance",
    "evaluation.metrics.custom_metric",
    "evaluation.metrics.datacompy_score",
    "evaluation.metrics.exact_match",
    "evaluation.metrics.factual_correctness",
    "evaluation.metrics.faithfulness",
    "evaluation.metrics.instance_rubrics",
    "evaluation.metrics.multi_llm_judge",
    "evaluation.metrics.noise_sensitivity",
    "evaluation.metrics.non_llm_string_similarity",
    "evaluation.metrics.response_groundedness",
    "evaluation.metrics.rouge_score",
    "evaluation.metrics.rubrics_score",
    "evaluation.metrics.semantic_similarity",
    "evaluation.metrics.sql_semantic_equivalence",
    "evaluation.metrics.string_presence",
    "evaluation.metrics.summarization_score",
    "evaluation.metrics.testgen",
    "evaluation.metrics.tool_call_accuracy",
    "evaluation.metrics.tool_call_f1",
    "evaluation.metrics.topic_adherence",
]


@pytest.mark.unit
@pytest.mark.parametrize("module", METRIC_MODULES)
def test_metric_module_importable(module: str) -> None:
    """Each evaluation metric module must be importable."""
    _import(module)


# ---------------------------------------------------------------------------
# Core application modules
# ---------------------------------------------------------------------------

CORE_MODULES = [
    "config",
    "db.init",
    "evaluation.scoring",
    "evaluation.suggestions",
]


@pytest.mark.unit
@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_importable(module: str) -> None:
    """Core app modules must be importable."""
    _import(module)


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_app_factory_creates_app() -> None:
    """The FastAPI app must be constructable without a running server."""
    from app import create_app
    application = create_app()
    assert application is not None
    assert application.title  # has a title set
