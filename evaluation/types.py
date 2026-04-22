from __future__ import annotations
from typing import TypedDict


class QuestionDict(TypedDict):
    user_input: str
    reference: str
    reference_contexts: list[str]
    synthesizer_name: str


class ContextDict(TypedDict):
    content: str


class ClaimDict(TypedDict):
    type: str  # "praise" | "critique"
    response_quote: str
    chunk_reference: str | None
    chunk_quote: str | None
    explanation: str


class EvaluatorResultDict(TypedDict):
    evaluator_index: int
    verdict: str  # "positive" | "mixed" | "critical"
    score: float
    reasoning: str
    claims: list[ClaimDict]
    model: str


class CriteriaHighlightDict(TypedDict):
    quote: str
    type: str  # "supporting" | "contradicting" | "neutral"
    critique: str


class CriteriaEvaluatorResultDict(TypedDict):
    evaluator_index: int
    verdict: str  # "good" | "mixed" | "bad"
    score: float  # 1.0 | 0.5 | 0.0
    highlights: list[CriteriaHighlightDict]
    reasoning: str
    model: str


class KGMetadata(TypedDict):
    id: int
    chunks_hash: str
    num_nodes: int
    num_chunks: int
    is_complete: bool
    completed_steps: int
    total_steps: int
    heartbeat_stale: bool


class PersonaDict(TypedDict):
    name: str
    description: str
