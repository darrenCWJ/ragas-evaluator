"""Dynamic custom metric evaluation using Ragas primitives.

Supports four metric types:
  - integer_range: DiscreteMetric with user prompt and configurable score range
  - similarity: DiscreteMetric comparing response vs reference
  - rubrics: RubricsScore with user-defined rubric descriptions
  - instance_rubrics: InstanceRubrics with per-question rubrics (stored on test questions)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ragas.metrics import DiscreteMetric, RubricsScore, InstanceRubrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CustomMetricConfig:
    """Immutable config for a single custom metric."""
    name: str
    metric_type: str  # integer_range | similarity | rubrics | instance_rubrics
    prompt: str | None = None
    rubrics: dict[str, str] | None = None
    min_score: int = 1
    max_score: int = 5


def create_scorer(config: CustomMetricConfig, llm):
    """Create a scorer object for the given custom metric config."""
    if config.metric_type == "rubrics":
        if not config.rubrics:
            raise ValueError(f"Custom metric '{config.name}' is rubrics type but has no rubrics defined")
        return RubricsScore(llm=llm, rubrics=config.rubrics)

    if config.metric_type == "instance_rubrics":
        return InstanceRubrics(llm=llm)

    if config.metric_type in ("integer_range", "similarity"):
        allowed = [str(i) for i in range(config.min_score, config.max_score + 1)]
        return DiscreteMetric(
            name=config.name,
            allowed_values=allowed,
            prompt=config.prompt,
        )

    raise ValueError(f"Unknown custom metric type: {config.metric_type}")


async def score_integer_range(
    scorer: DiscreteMetric,
    llm,
    question: str,
    answer: str,
    contexts: list[str] | None = None,
    reference: str | None = None,
) -> float:
    """Score using DiscreteMetric for integer_range type."""
    result = await scorer.ascore(
        llm=llm,
        response=answer,
        user_input=question,
        reference=reference or "",
        retrieved_contexts="\n".join(contexts) if contexts else "",
    )
    return float(result.value)


async def score_similarity(
    scorer: DiscreteMetric,
    llm,
    answer: str,
    reference: str,
) -> float:
    """Score using DiscreteMetric for similarity type."""
    result = await scorer.ascore(
        llm=llm,
        response=answer,
        reference=reference,
    )
    return float(result.value)


async def score_rubrics(
    scorer: RubricsScore,
    question: str,
    answer: str,
    contexts: list[str] | None = None,
) -> float:
    """Score using RubricsScore."""
    from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts or [],
    )
    return await scorer.single_turn_ascore(sample)


async def score_instance_rubrics(
    scorer: InstanceRubrics,
    question: str,
    answer: str,
    reference: str,
    rubrics: dict[str, str],
    contexts: list[str] | None = None,
) -> float:
    """Score using InstanceRubrics with per-question rubrics."""
    from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        reference=reference,
        retrieved_contexts=contexts or [],
        rubrics=rubrics,
    )
    return await scorer.single_turn_ascore(sample)
