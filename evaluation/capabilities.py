"""Dataset-capability model: which metrics can run on which test sets.

Single source of truth for metric/dataset compatibility. The frontend pulls
this via the capabilities endpoint to gray out unavailable metrics at
selection time, and the experiment run route enforces it server-side.

Capabilities are derived from the approved questions of a test set:

- ``contexts``  — at least one question carries reference contexts
- ``category``  — questions are tagged with categories (refusal tagging)
- ``turns``     — multi-turn conversation data in metadata
- ``ref_sql``   — reference SQL for SQL-equivalence scoring
- ``ref_data``  — reference structured data for datacompy scoring

``contexts`` can also be satisfied at runtime (internal RAG pipelines always
retrieve; some bot connectors return their contexts) — callers pass
``runtime_contexts=True`` for that.
"""

from __future__ import annotations

CONTEXTS = "contexts"
CATEGORY = "category"
TURNS = "turns"
REF_SQL = "ref_sql"
REF_DATA = "ref_data"
REF_TOOL_CALLS = "ref_tool_calls"

# Human-readable labels for missing-capability messages.
CAPABILITY_LABELS = {
    CONTEXTS: "retrieved or reference contexts",
    CATEGORY: "question categories",
    TURNS: "multi-turn conversation data",
    REF_SQL: "reference SQL",
    REF_DATA: "reference data",
    REF_TOOL_CALLS: "reference tool calls",
}

# Dataset requirements per built-in metric. Metrics not listed here (and all
# custom metrics) only need a question + reference answer, which every test
# set has by construction.
METRIC_REQUIREMENTS: dict[str, frozenset[str]] = {
    "faithfulness": frozenset({CONTEXTS}),
    "context_precision": frozenset({CONTEXTS}),
    "context_recall": frozenset({CONTEXTS}),
    "context_entities_recall": frozenset({CONTEXTS}),
    "noise_sensitivity": frozenset({CONTEXTS}),
    "summarization_score": frozenset({CONTEXTS}),
    "context_relevance": frozenset({CONTEXTS}),
    "response_groundedness": frozenset({CONTEXTS}),
    "aspect_critic": frozenset({CONTEXTS}),
    "rubrics_score": frozenset({CONTEXTS}),
    "instance_rubrics": frozenset({CONTEXTS}),
    "refusal_accuracy": frozenset({CATEGORY}),
    "conversation_retention": frozenset({TURNS}),
    "sql_semantic_equivalence": frozenset({REF_SQL}),
    "datacompy_score": frozenset({REF_DATA}),
}


def dataset_capabilities(conn, test_set_id: int) -> set[str]:
    """Compute the capability set from a test set's approved/edited questions."""
    row = conn.execute(
        """
        SELECT
            MAX(CASE WHEN (reference_contexts IS NOT NULL
                           AND reference_contexts != '[]'
                           AND reference_contexts != '')
                       OR (user_edited_contexts IS NOT NULL
                           AND user_edited_contexts != '[]'
                           AND user_edited_contexts != '') THEN 1 ELSE 0 END) AS has_ctx,
            MAX(CASE WHEN category IS NOT NULL AND category != '' THEN 1 ELSE 0 END) AS has_category,
            MAX(CASE WHEN metadata_json IS NOT NULL
                          AND metadata_json LIKE '%"turns"%' THEN 1 ELSE 0 END) AS has_turns,
            MAX(CASE WHEN metadata_json IS NOT NULL
                          AND metadata_json LIKE '%reference_sql%' THEN 1 ELSE 0 END) AS has_ref_sql,
            MAX(CASE WHEN metadata_json IS NOT NULL
                          AND metadata_json LIKE '%reference_data%' THEN 1 ELSE 0 END) AS has_ref_data,
            MAX(CASE WHEN metadata_json IS NOT NULL
                          AND metadata_json LIKE '%reference_tool_calls%' THEN 1 ELSE 0 END) AS has_ref_tool_calls
        FROM test_questions
        WHERE test_set_id = ? AND status IN ('approved', 'edited')
        """,
        (test_set_id,),
    ).fetchone()

    caps: set[str] = set()
    if row is None:
        return caps
    if row["has_ctx"]:
        caps.add(CONTEXTS)
    if row["has_category"]:
        caps.add(CATEGORY)
    if row["has_turns"]:
        caps.add(TURNS)
    if row["has_ref_sql"]:
        caps.add(REF_SQL)
    if row["has_ref_data"]:
        caps.add(REF_DATA)
    if row["has_ref_tool_calls"]:
        caps.add(REF_TOOL_CALLS)
    return caps


def metric_availability(
    capabilities: set[str],
    runtime_contexts: bool = False,
) -> dict[str, dict]:
    """Per-metric availability for a capability set.

    Returns ``{metric: {"available": bool, "missing": [labels]}}`` for every
    built-in metric. ``runtime_contexts=True`` marks the contexts requirement
    satisfied by the pipeline (internal RAG, or a bot that returns contexts).
    """
    from evaluation.scoring import ALL_METRICS

    effective = set(capabilities)
    if runtime_contexts:
        effective.add(CONTEXTS)

    result: dict[str, dict] = {}
    for metric in ALL_METRICS:
        missing = METRIC_REQUIREMENTS.get(metric, frozenset()) - effective
        result[metric] = {
            "available": not missing,
            "missing": sorted(CAPABILITY_LABELS[m] for m in missing),
        }
    return result
