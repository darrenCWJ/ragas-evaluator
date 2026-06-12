"""Suggestion generation engine and config-change application helpers."""

import statistics

# Import from config module directly to avoid circular import through app/__init__.py
import config as _cfg

SUGGESTION_HIGH_THRESHOLD = _cfg.SUGGESTION_HIGH_THRESHOLD
SUGGESTION_MEDIUM_THRESHOLD = _cfg.SUGGESTION_MEDIUM_THRESHOLD
VALID_RESPONSE_MODES = _cfg.VALID_RESPONSE_MODES
VALID_SEARCH_TYPES = _cfg.VALID_SEARCH_TYPES

# ---------------------------------------------------------------------------
# Prompt guardrail library
# ---------------------------------------------------------------------------
# Ready-to-apply system-prompt additions, each tied to the failure signal it
# fixes. For internal RAG configs they apply directly (system_prompt_append);
# for external agents the user copies them into their own agent's prompt.

GUARDRAIL_SNIPPETS: dict[str, str] = {
    "grounding": (
        "GROUNDING RULES:\n"
        "- Answer ONLY using facts stated in the provided context.\n"
        "- Never add information from outside the context, even if you believe it is true.\n"
        "- If the context only partially answers the question, answer the part that is "
        "covered and explicitly say what is not covered."
    ),
    "refusal": (
        "WHEN THE ANSWER IS NOT IN THE CONTEXT:\n"
        "- If the provided context does not contain the answer, say so plainly "
        "(e.g. \"I don't have information about that in the knowledge base\").\n"
        "- Do NOT guess, extrapolate, or fabricate an answer.\n"
        "- Where possible, point the user to what related information IS available."
    ),
    "noise_filter": (
        "CONTEXT FILTERING:\n"
        "- Some retrieved passages may be irrelevant to the question. Identify and ignore them.\n"
        "- Base your answer only on the passages that directly address the question.\n"
        "- Do not let unrelated passages change or dilute your answer."
    ),
    "directness": (
        "ANSWER STYLE:\n"
        "- Answer the question that was asked, directly, in the first sentence.\n"
        "- Add supporting detail after the direct answer, not before.\n"
        "- Do not pad responses with generic introductions or repetition of the question."
    ),
    "phased_reasoning": (
        "REASONING STEPS (follow in order):\n"
        "1. Identify what the question is asking and which entities/values are involved.\n"
        "2. Locate every context passage relevant to each entity.\n"
        "3. Combine the facts across passages, resolving conflicts by preferring the most "
        "specific passage.\n"
        "4. State the final answer, then list which passages support it."
    ),
    "persona": (
        "ROLE:\n"
        "You are a precise, factual assistant for this knowledge base. You value accuracy "
        "over completeness: a short correct answer beats a long speculative one. You write "
        "for a busy reader — plain language, no filler."
    ),
    "clarify_edge": (
        "AMBIGUOUS OR EDGE-CASE QUESTIONS:\n"
        "- If a question is ambiguous, state the interpretation you are answering under.\n"
        "- If a question asks about an exception or boundary condition, answer the specific "
        "case asked — do not substitute the general rule."
    ),
}


def generate_suggestions(
    aggregate_metrics: dict, per_question_results: list[dict]
) -> list[dict]:
    """Rule-based suggestion engine: analyzes metrics and returns actionable suggestions."""
    suggestions = []

    if not aggregate_metrics:
        return suggestions

    def _priority(score):
        if score < SUGGESTION_HIGH_THRESHOLD:
            return "high"
        elif score < SUGGESTION_MEDIUM_THRESHOLD:
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

    # --- Generation / prompt-guardrail rules ---
    faithfulness = aggregate_metrics.get("faithfulness")
    if faithfulness is not None and faithfulness < 0.7:
        suggestions.append({
            "category": "guardrail",
            "signal": f"faithfulness avg {faithfulness:.2f}",
            "suggestion": (
                "Responses contain claims not supported by the retrieved context — "
                "add grounding rules to the system prompt (Apply appends them; for an "
                "external agent, copy them into its prompt)"
            ),
            "priority": _priority(faithfulness),
            "config_field": "system_prompt_append",
            "suggested_value": GUARDRAIL_SNIPPETS["grounding"],
        })

    refusal_accuracy = aggregate_metrics.get("refusal_accuracy")
    if refusal_accuracy is not None and refusal_accuracy < 0.7:
        suggestions.append({
            "category": "guardrail",
            "signal": f"refusal_accuracy avg {refusal_accuracy:.2f}",
            "suggestion": (
                "The agent fabricates answers to out-of-scope questions instead of "
                "declining — add an explicit refusal guardrail to the system prompt"
            ),
            "priority": "high" if refusal_accuracy < 0.5 else "medium",
            "config_field": "system_prompt_append",
            "suggested_value": GUARDRAIL_SNIPPETS["refusal"],
        })

    # ragas noise_sensitivity is an error rate — LOWER is better.
    noise_sensitivity = aggregate_metrics.get("noise_sensitivity")
    if noise_sensitivity is not None and noise_sensitivity > 0.3:
        suggestions.append({
            "category": "guardrail",
            "signal": f"noise_sensitivity avg {noise_sensitivity:.2f} (lower is better)",
            "suggestion": (
                "Irrelevant retrieved passages are leaking into answers — add a "
                "context-filtering instruction, or enable reranking to cut the noise "
                "before it reaches the model"
            ),
            "priority": "high" if noise_sensitivity > 0.5 else "medium",
            "config_field": "system_prompt_append",
            "suggested_value": GUARDRAIL_SNIPPETS["noise_filter"],
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
        suggestions.append({
            "category": "guardrail",
            "signal": f"answer_relevancy avg {answer_relevancy:.2f}",
            "suggestion": (
                "Responses drift around the question — add a persona and answer-first "
                "style rule to the system prompt"
            ),
            "priority": _priority(answer_relevancy),
            "config_field": "system_prompt_append",
            "suggested_value": GUARDRAIL_SNIPPETS["persona"] + "\n\n" + GUARDRAIL_SNIPPETS["directness"],
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

        suggestions.extend(_category_rules(per_question_results))

    return suggestions


# Category → the prompt fix that addresses that category's typical failure.
_CATEGORY_FIXES: dict[str, tuple[str, str]] = {
    "out_of_knowledge_base": ("refusal", "add a refusal guardrail so it declines instead of fabricating"),
    "edge": ("clarify_edge", "add an edge-case instruction (state interpretation, answer the specific case)"),
    "multi_hop": ("phased_reasoning", "add step-by-step reasoning phases to the prompt (and consider multi_step response mode)"),
}


def _category_rules(per_question_results: list[dict]) -> list[dict]:
    """Flag question categories that score well below the experiment average.

    Results may carry a "category" key (the analyze route joins it in). For
    each weak category we suggest the prompt fix that targets that failure
    mode rather than a generic knob tweak.
    """
    def _mean_score(metrics: dict) -> float | None:
        vals = [v for v in metrics.values() if v is not None]
        return sum(vals) / len(vals) if vals else None

    by_category: dict[str, list[float]] = {}
    all_scores: list[float] = []
    for r in per_question_results:
        score = _mean_score(r.get("metrics", {}))
        if score is None:
            continue
        all_scores.append(score)
        category = (r.get("category") or "").strip()
        if category:
            by_category.setdefault(category, []).append(score)

    if len(all_scores) < 5:
        return []
    overall = sum(all_scores) / len(all_scores)

    out: list[dict] = []
    for category, scores in by_category.items():
        if len(scores) < 3:
            continue
        cat_mean = sum(scores) / len(scores)
        if cat_mean >= overall - 0.2:
            continue
        fix_key = next(
            (snippet for prefix, (snippet, _) in _CATEGORY_FIXES.items() if category.startswith(prefix)),
            None,
        )
        fix_hint = next(
            (hint for prefix, (_, hint) in _CATEGORY_FIXES.items() if category.startswith(prefix)),
            "inspect these questions in the category breakdown to find the shared failure",
        )
        out.append({
            "category": "category_gap",
            "signal": f"'{category}' questions avg {cat_mean:.2f} vs {overall:.2f} overall ({len(scores)} questions)",
            "suggestion": f"The agent is weakest on '{category}' questions — {fix_hint}",
            "priority": "high" if cat_mean < overall - 0.35 else "medium",
            "config_field": "system_prompt_append" if fix_key else None,
            "suggested_value": GUARDRAIL_SNIPPETS[fix_key] if fix_key else None,
        })
    return out


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
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid max_steps value: '{value_to_use}'. Must be integer 1-10."
            ) from e
        if new_value < 1 or new_value > 10:
            raise ValueError("max_steps must be between 1 and 10")

    elif config_field == "alpha":
        if value_to_use is None:
            raise ValueError("alpha requires a value")
        try:
            new_value = float(value_to_use)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid alpha value: '{value_to_use}'. Must be float 0.0-1.0."
            ) from e
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

    elif config_field == "system_prompt_append":
        # Guardrail suggestions append to the existing prompt rather than
        # replacing it. The change is recorded against system_prompt so the
        # cloned config picks it up like any other field.
        if value_to_use is None:
            raise ValueError("system_prompt_append requires the guardrail text")
        old_value = config_row.get("system_prompt") or ""
        if value_to_use.strip() in old_value:
            raise ValueError("This guardrail is already part of the system prompt")
        new_value = f"{old_value}\n\n{value_to_use}".strip()
        changes = {"system_prompt": {"old": old_value, "new": new_value}}
        return {"system_prompt": new_value}, changes

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
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid {config_field} value: '{value_to_use}'. Must be an integer ID."
            ) from e

    else:
        if value_to_use is not None:
            new_value = value_to_use

    changes = {config_field: {"old": old_value, "new": new_value}}
    return {config_field: new_value}, changes
