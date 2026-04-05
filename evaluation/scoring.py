"""Metric scorer setup and evaluation helpers."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory

from evaluation.metrics import custom_metric
from evaluation.metrics.custom_metric import CustomMetricConfig

from evaluation.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    context_entities_recall,
    noise_sensitivity,
    factual_correctness,
    semantic_similarity,
    non_llm_string_similarity,
    bleu_score,
    rouge_score,
    chrf_score,
    exact_match,
    string_presence,
    summarization_score,
    aspect_critic,
    rubrics_score,
    answer_accuracy,
    context_relevance,
    response_groundedness,
)

logger = logging.getLogger(__name__)

ALL_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "context_entities_recall",
    "noise_sensitivity",
    "factual_correctness",
    "semantic_similarity",
    "non_llm_string_similarity",
    "bleu_score",
    "rouge_score",
    "chrf_score",
    "exact_match",
    "string_presence",
    "summarization_score",
    "aspect_critic",
    "rubrics_score",
    "answer_accuracy",
    "context_relevance",
    "response_groundedness",
]

# Maps metric name → module for dynamic dispatch
_METRIC_MODULES = {
    "faithfulness": faithfulness,
    "answer_relevancy": answer_relevancy,
    "context_precision": context_precision,
    "context_recall": context_recall,
    "context_entities_recall": context_entities_recall,
    "noise_sensitivity": noise_sensitivity,
    "factual_correctness": factual_correctness,
    "semantic_similarity": semantic_similarity,
    "non_llm_string_similarity": non_llm_string_similarity,
    "bleu_score": bleu_score,
    "rouge_score": rouge_score,
    "chrf_score": chrf_score,
    "exact_match": exact_match,
    "string_presence": string_presence,
    "summarization_score": summarization_score,
    "aspect_critic": aspect_critic,
    "rubrics_score": rubrics_score,
    "answer_accuracy": answer_accuracy,
    "context_relevance": context_relevance,
    "response_groundedness": response_groundedness,
}

# Metrics that need only LLM
_LLM_ONLY = {
    "faithfulness", "context_precision", "context_recall",
    "context_entities_recall", "noise_sensitivity", "factual_correctness",
    "summarization_score", "aspect_critic", "rubrics_score",
    "answer_accuracy", "context_relevance", "response_groundedness",
}
# Metrics that need LLM + embeddings
_LLM_AND_EMBED = {"answer_relevancy"}
# Metrics that need only embeddings
_EMBED_ONLY = {"semantic_similarity"}
# Metrics that need nothing
_NO_DEPS = {
    "non_llm_string_similarity", "bleu_score", "rouge_score",
    "chrf_score", "exact_match", "string_presence",
}


def setup_scorers(
    metrics: list[str] | None = None,
    custom_configs: list[CustomMetricConfig] | None = None,
) -> tuple[dict, dict, object]:
    """Set up built-in + custom metric scorers.

    Returns (builtin_scorers, custom_scorers, llm).
    The llm is returned so custom DiscreteMetric scorers can use it at score time.
    """
    selected = metrics or ALL_METRICS
    client = AsyncOpenAI()
    llm = llm_factory("gpt-4o-mini", client=client, max_tokens=16384)
    embeddings = embedding_factory(
        "openai", model="text-embedding-3-small", client=client
    )

    scorers = {}
    for m in selected:
        if m in _LLM_ONLY:
            scorers[m] = _METRIC_MODULES[m].create_scorer(llm)
        elif m in _LLM_AND_EMBED:
            scorers[m] = _METRIC_MODULES[m].create_scorer(llm, embeddings)
        elif m in _EMBED_ONLY:
            scorers[m] = _METRIC_MODULES[m].create_scorer(embeddings)
        elif m in _NO_DEPS:
            scorers[m] = _METRIC_MODULES[m].create_scorer()

    custom_scorers = {}
    for cfg in (custom_configs or []):
        try:
            custom_scorers[cfg.name] = (cfg, custom_metric.create_scorer(cfg, llm))
        except Exception as e:
            logger.warning("Failed to create custom scorer '%s': %s", cfg.name, e)

    return scorers, custom_scorers, llm


# Signature patterns for score() calls — grouped by argument shape
_SCORE_SIGNATURES = {
    # (scorer, question, answer, contexts)
    "q_a_ctx": {
        "faithfulness", "context_precision", "context_recall",
        "aspect_critic", "rubrics_score",
    },
    # (scorer, question, answer)
    "q_a": {"answer_relevancy"},
    # (scorer, answer, contexts)
    "a_ctx": {
        "context_entities_recall", "summarization_score",
        "response_groundedness",
    },
    # (scorer, question, answer, reference, contexts)
    "q_a_ref_ctx": {"noise_sensitivity"},
    # (scorer, answer, reference)
    "a_ref": {
        "factual_correctness", "semantic_similarity",
        "non_llm_string_similarity", "bleu_score", "rouge_score",
        "chrf_score", "exact_match", "string_presence",
    },
    # (scorer, question, answer, reference)
    "q_a_ref": {"answer_accuracy"},
    # (scorer, question, contexts)
    "q_ctx": {"context_relevance"},
}


async def evaluate_experiment_row(
    scorers: dict,
    question: str,
    generated_answer: str,
    reference_answer: str,
    contexts: list[str],
    custom_scorers: dict | None = None,
    llm=None,
) -> dict:
    """Evaluate a generated answer against reference using selected metrics."""
    results = {}

    for name, scorer in scorers.items():
        try:
            mod = _METRIC_MODULES[name]
            if name in _SCORE_SIGNATURES["q_a_ctx"]:
                results[name] = await mod.score(
                    scorer, question, generated_answer, contexts
                )
            elif name in _SCORE_SIGNATURES["q_a"]:
                results[name] = await mod.score(scorer, question, generated_answer)
            elif name in _SCORE_SIGNATURES["a_ctx"]:
                results[name] = await mod.score(scorer, generated_answer, contexts)
            elif name in _SCORE_SIGNATURES["q_a_ref_ctx"]:
                results[name] = await mod.score(
                    scorer, question, generated_answer, reference_answer, contexts
                )
            elif name in _SCORE_SIGNATURES["a_ref"]:
                results[name] = await mod.score(
                    scorer, generated_answer, reference_answer
                )
            elif name in _SCORE_SIGNATURES["q_a_ref"]:
                results[name] = await mod.score(
                    scorer, question, generated_answer, reference_answer
                )
            elif name in _SCORE_SIGNATURES["q_ctx"]:
                results[name] = await mod.score(scorer, question, contexts)
        except Exception as e:
            logger.warning("Metric %s failed: %s", name, e)
            results[name] = None

    # Evaluate custom metrics
    for name, (cfg, scorer) in (custom_scorers or {}).items():
        try:
            if cfg.metric_type == "integer_range":
                results[name] = await custom_metric.score_integer_range(
                    scorer, llm, question, generated_answer, contexts, reference_answer,
                )
            elif cfg.metric_type == "similarity":
                results[name] = await custom_metric.score_similarity(
                    scorer, llm, generated_answer, reference_answer,
                )
            elif cfg.metric_type == "rubrics":
                results[name] = await custom_metric.score_rubrics(
                    scorer, question, generated_answer, contexts,
                )
            elif cfg.metric_type == "instance_rubrics":
                # Instance rubrics need per-question rubrics — skip if none provided
                logger.info("Skipping instance_rubrics metric '%s' (per-question rubrics not yet supported in runner)", name)
                results[name] = None
        except Exception as e:
            logger.warning("Custom metric %s failed: %s", name, e)
            results[name] = None

    return results
