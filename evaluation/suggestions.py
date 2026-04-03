"""Suggestion generation engine and config-change application helpers."""

import statistics

# Duplicated from app.models to avoid circular import (evaluation ↔ app)
VALID_RESPONSE_MODES = {"single_shot", "multi_step"}
VALID_SEARCH_TYPES = {"dense", "sparse", "hybrid"}


def generate_suggestions(
    aggregate_metrics: dict, per_question_results: list[dict]
) -> list[dict]:
    """Rule-based suggestion engine: analyzes metrics and returns actionable suggestions."""
    suggestions = []

    if not aggregate_metrics:
        return suggestions

    def _priority(score):
        if score < 0.4:
            return "high"
        elif score < 0.7:
            return "medium"
        else:
            return "low"

    # --- Retrieval rules ---
    context_recall = aggregate_metrics.get("context_recall")
    if context_recall is not None and context_recall < 0.7:
        suggestions.append({
            "category": "retrieval",
            "signal": f"context_recall avg {context_recall:.2f}",
            "suggestion": "Consider increasing top_k, adding hybrid search, or re-chunking with smaller chunk sizes for better recall",
            "priority": _priority(context_recall),
            "config_field": "top_k",
            "suggested_value": "+5",
        })

    context_precision = aggregate_metrics.get("context_precision")
    if context_precision is not None and context_precision < 0.7:
        suggestions.append({
            "category": "retrieval",
            "signal": f"context_precision avg {context_precision:.2f}",
            "suggestion": "Retrieved contexts are noisy — try reranking, reduce top_k, or use more specific embedding model",
            "priority": _priority(context_precision),
            "config_field": "top_k",
            "suggested_value": "-2",
        })

    context_relevance = aggregate_metrics.get("context_relevance")
    if context_relevance is not None and context_relevance < 0.5:
        suggestions.append({
            "category": "retrieval",
            "signal": f"context_relevance avg {context_relevance:.2f}",
            "suggestion": "Contexts are not relevant — review embedding model choice or chunking strategy",
            "priority": _priority(context_relevance),
            "config_field": "embedding_config_id",
            "suggested_value": None,
        })

    # --- Generation rules ---
    faithfulness = aggregate_metrics.get("faithfulness")
    if faithfulness is not None and faithfulness < 0.7:
        suggestions.append({
            "category": "generation",
            "signal": f"faithfulness avg {faithfulness:.2f}",
            "suggestion": "Responses contain unsupported claims — add system prompt instruction to only use provided context",
            "priority": _priority(faithfulness),
            "config_field": "system_prompt",
            "suggested_value": None,
        })

    answer_relevancy = aggregate_metrics.get("answer_relevancy")
    if answer_relevancy is not None and answer_relevancy < 0.7:
        suggestions.append({
            "category": "generation",
            "signal": f"answer_relevancy avg {answer_relevancy:.2f}",
            "suggestion": "Responses are not addressing the question — check system prompt clarity and response_mode",
            "priority": _priority(answer_relevancy),
            "config_field": "response_mode",
            "suggested_value": "multi_step",
        })

    answer_correctness = aggregate_metrics.get("answer_correctness")
    if answer_correctness is not None and answer_correctness < 0.5:
        suggestions.append({
            "category": "generation",
            "signal": f"answer_correctness avg {answer_correctness:.2f}",
            "suggestion": "Low correctness — verify reference answers are accurate, then review retrieval quality",
            "priority": _priority(answer_correctness),
            "config_field": None,
            "suggested_value": None,
        })

    # --- Embedding rules (cross-metric) ---
    if (
        context_recall is not None
        and context_recall < 0.5
        and context_precision is not None
        and context_precision < 0.5
    ):
        suggestions.append({
            "category": "embedding",
            "signal": f"context_recall {context_recall:.2f} AND context_precision {context_precision:.2f}",
            "suggestion": "Both recall and precision low — embedding model may be mismatched for this domain. Try a different model or fine-tune",
            "priority": "high",
            "config_field": "embedding_config_id",
            "suggested_value": None,
        })

    # --- Chunking rules (variance-based) ---
    if per_question_results:
        metric_scores: dict[str, list[float]] = {}
        for r in per_question_results:
            metrics = r.get("metrics", {})
            for mn, val in metrics.items():
                if val is not None:
                    metric_scores.setdefault(mn, []).append(val)

        high_variance_metrics: list[str] = []
        for mn, scores in metric_scores.items():
            if len(scores) >= 3:
                stdev = statistics.stdev(scores)
                if stdev > 0.3:
                    high_variance_metrics.append(f"{mn} (stdev {stdev:.2f})")

        if high_variance_metrics:
            signal_parts = ", ".join(high_variance_metrics)
            count = len(high_variance_metrics)
            suggestions.append({
                "category": "chunking",
                "signal": f"High variance in {signal_parts}",
                "suggestion": f"Inconsistent scores across questions in {count} metric{'s' if count > 1 else ''} — try a different chunking config for more uniform results",
                "priority": "medium" if count < 3 else "high",
                "config_field": "chunk_config_id",
                "suggested_value": None,
            })

    return suggestions


# Fields where override_value must be validated as a specific type
_NUMERIC_CONFIG_FIELDS = {"top_k", "alpha", "max_steps"}
_ENUM_CONFIG_FIELDS = {
    "response_mode": VALID_RESPONSE_MODES,
    "search_type": VALID_SEARCH_TYPES,
}


def apply_config_change(
    config_row: dict,
    config_field: str,
    suggested_value: str | None,
    override_value: str | None,
) -> tuple[dict, dict]:
    """Apply a suggestion's config change to a cloned config dict.

    Returns (updated_fields_dict, changes_dict) where changes_dict is {field: {old, new}}.
    """
    value_to_use = override_value if override_value is not None else suggested_value
    old_value = config_row.get(config_field)
    new_value = old_value

    if config_field == "top_k":
        current = config_row["top_k"]
        if (
            value_to_use is not None
            and value_to_use.lstrip("+-").isdigit()
            and (value_to_use.startswith("+") or value_to_use.startswith("-"))
        ):
            new_value = current + int(value_to_use)
        elif value_to_use is not None and value_to_use.isdigit():
            new_value = int(value_to_use)
        else:
            raise ValueError(
                f"Invalid top_k value: '{value_to_use}'. Use relative (+5, -2) or absolute (10) integer."
            )
        new_value = max(1, min(50, new_value))

    elif config_field == "max_steps":
        if value_to_use is None:
            raise ValueError("max_steps requires a value")
        try:
            new_value = int(value_to_use)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid max_steps value: '{value_to_use}'. Must be integer 1-10."
            )
        if new_value < 1 or new_value > 10:
            raise ValueError("max_steps must be between 1 and 10")

    elif config_field == "alpha":
        if value_to_use is None:
            raise ValueError("alpha requires a value")
        try:
            new_value = float(value_to_use)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid alpha value: '{value_to_use}'. Must be float 0.0-1.0."
            )
        if new_value < 0.0 or new_value > 1.0:
            raise ValueError("alpha must be between 0.0 and 1.0")

    elif config_field in _ENUM_CONFIG_FIELDS:
        allowed = _ENUM_CONFIG_FIELDS[config_field]
        if value_to_use is not None and value_to_use in allowed:
            new_value = value_to_use
        elif value_to_use is not None:
            raise ValueError(
                f"Invalid {config_field} value: '{value_to_use}'. "
                f"Must be one of: {', '.join(sorted(allowed))}"
            )
        else:
            raise ValueError(
                f"{config_field} requires a value. Provide override_value as one of: "
                f"{', '.join(sorted(allowed))}"
            )

    elif config_field == "system_prompt":
        if value_to_use is None:
            raise ValueError(
                "system_prompt requires an override_value with the new prompt text"
            )
        new_value = value_to_use

    elif config_field in ("embedding_config_id", "chunk_config_id"):
        if value_to_use is None:
            label = (
                "chunking config"
                if config_field == "chunk_config_id"
                else "embedding config"
            )
            raise ValueError(f"Please select a {label} from the dropdown")
        try:
            new_value = int(value_to_use)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid {config_field} value: '{value_to_use}'. Must be an integer ID."
            )

    else:
        if value_to_use is not None:
            new_value = value_to_use

    changes = {config_field: {"old": old_value, "new": new_value}}
    return {config_field: new_value}, changes
