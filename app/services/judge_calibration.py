"""Judge calibration: rank judge models by agreement with human annotations.

The annotation workflow collects human ratings (accurate / partially_accurate /
inaccurate) on a 20% sample of experiment results. Each multi-LLM-judge
evaluation now records which model produced it, so across a project we can
pair every human-rated result with the per-model judge scores for the same
result and measure which judge model agrees with humans most. The winner(s)
can be applied as the project's default judge assignments.

Older evaluations (before the model column existed) have model=NULL and are
excluded from calibration.
"""

import json
import logging

from logging_utils import clean

logger = logging.getLogger(__name__)

# Same buckets the per-experiment evaluator-accuracy view uses.
RATING_SCORES = {"accurate": 1.0, "partially_accurate": 0.5, "inaccurate": 0.0}

# A model needs at least this many human-paired evaluations to be ranked.
MIN_CALIBRATION_PAIRS = 5

# Models agreeing with humans less than half the time are never recommended.
MIN_RECOMMEND_AGREEMENT = 0.5

# Default judge panel size when applying a recommendation.
DEFAULT_PANEL_SIZE = 3


def _bucket(score: float) -> str:
    if score >= 0.7:
        return "accurate"
    if score >= 0.4:
        return "partially_accurate"
    return "inaccurate"


def judge_calibration_report(conn, project_id: int) -> dict:
    """Project-wide per-judge-model agreement with human annotations."""
    rows = conn.execute(
        """SELECT ha.rating, mle.model, mle.score
           FROM human_annotations ha
           JOIN experiment_results er ON ha.experiment_result_id = er.id
           JOIN experiments e ON er.experiment_id = e.id
           JOIN multi_llm_evaluations mle ON mle.experiment_result_id = er.id
           WHERE e.project_id = ?
             AND mle.custom_metric_name IS NULL
             AND mle.model IS NOT NULL""",
        (project_id,),
    ).fetchall()

    per_model: dict[str, dict] = {}
    for row in rows:
        human_score = RATING_SCORES.get(row["rating"])
        if human_score is None:
            continue
        stats = per_model.setdefault(
            row["model"], {"pairs": 0, "agreements": 0, "abs_error_sum": 0.0}
        )
        stats["pairs"] += 1
        stats["abs_error_sum"] += abs(row["score"] - human_score)
        if _bucket(row["score"]) == row["rating"]:
            stats["agreements"] += 1

    models = []
    for model, stats in per_model.items():
        models.append({
            "model": model,
            "pairs": stats["pairs"],
            "agreement_rate": round(stats["agreements"] / stats["pairs"], 4),
            "mean_abs_error": round(stats["abs_error_sum"] / stats["pairs"], 4),
            "calibrated": stats["pairs"] >= MIN_CALIBRATION_PAIRS,
        })
    # Best agreement first; tie-break on lower mean absolute error, then volume.
    models.sort(key=lambda m: (-m["agreement_rate"], m["mean_abs_error"], -m["pairs"]))

    ranked = [
        m["model"]
        for m in models
        if m["calibrated"] and m["agreement_rate"] >= MIN_RECOMMEND_AGREEMENT
    ]
    recommendation = ranked[:DEFAULT_PANEL_SIZE] if ranked else None

    return {
        "project_id": project_id,
        "total_pairs": sum(m["pairs"] for m in models),
        "min_pairs_required": MIN_CALIBRATION_PAIRS,
        "models": models,
        "recommended_assignments": recommendation,
    }


def apply_judge_assignments(conn, project_id: int, models: list[str]) -> list[str]:
    """Persist judge model assignments as the project default."""
    conn.execute(
        "UPDATE projects SET judge_model_assignments_json = ? WHERE id = ?",
        (json.dumps(models), project_id),
    )
    conn.commit()
    logger.info("Project %d judge assignments set to %s", project_id, clean(models))
    return models
