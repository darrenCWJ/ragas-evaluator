"""Human annotation routes for evaluator accuracy validation."""

import json
import logging
import random

from fastapi import APIRouter, HTTPException

from app.models import HumanAnnotationBatch
import db.init

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["annotations"])

# Rating-to-score mapping for agreement computation
_RATING_SCORES = {"accurate": 1.0, "partially_accurate": 0.5, "inaccurate": 0.0}

# Metric names that represent "correctness" for agreement comparison
_CORRECTNESS_METRICS = [
    "factual_correctness",
    "faithfulness",
    "answer_relevancy",
    "semantic_similarity",
]


def _validate_experiment(conn, project_id: int, experiment_id: int):
    """Return the experiment row or raise 404."""
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be completed (current: {experiment['status']})",
        )

    return experiment


@router.get("/projects/{project_id}/experiments/{experiment_id}/annotation-sample")
async def get_annotation_sample(project_id: int, experiment_id: int):
    """Return a 20% random sample of experiment results for human annotation.

    Results that already have annotations are included but flagged so the
    frontend can show progress.
    """
    conn = db.init.get_db()
    _validate_experiment(conn, project_id, experiment_id)

    # Fetch all results for this experiment
    all_results = conn.execute(
        """SELECT er.id, er.test_question_id, er.response, er.metrics_json,
                  tq.question, tq.reference_answer, tq.user_edited_answer
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id""",
        (experiment_id,),
    ).fetchall()

    total = len(all_results)
    if total == 0:
        return {"experiment_id": experiment_id, "total_results": 0, "sample_size": 0, "sample": []}

    # 20% sample, minimum 1
    sample_size = max(1, round(total * 0.2))

    # Deterministic seed so the same experiment always gets the same sample
    rng = random.Random(experiment_id)
    sample_indices = sorted(rng.sample(range(total), sample_size))
    sampled_rows = [all_results[i] for i in sample_indices]

    # Fetch existing annotations for sampled results
    sample_ids = [r["id"] for r in sampled_rows]
    placeholders = ",".join("?" for _ in sample_ids)
    existing_annotations = conn.execute(
        f"SELECT * FROM human_annotations WHERE experiment_result_id IN ({placeholders})",
        sample_ids,
    ).fetchall()
    annotation_map = {a["experiment_result_id"]: a for a in existing_annotations}

    sample = []
    for r in sampled_rows:
        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        metrics = json.loads(r["metrics_json"]) if r["metrics_json"] else {}

        annotation = annotation_map.get(r["id"])
        sample.append({
            "experiment_result_id": r["id"],
            "test_question_id": r["test_question_id"],
            "question": r["question"],
            "reference_answer": ref_answer,
            "response": r["response"],
            "metrics": metrics,
            "annotation": {
                "rating": annotation["rating"],
                "notes": annotation["notes"],
                "annotated_at": annotation["annotated_at"],
            } if annotation else None,
        })

    annotated_count = sum(1 for s in sample if s["annotation"] is not None)

    return {
        "experiment_id": experiment_id,
        "total_results": total,
        "sample_size": sample_size,
        "annotated_count": annotated_count,
        "sample": sample,
    }


@router.post("/projects/{project_id}/experiments/{experiment_id}/annotations")
async def submit_annotations(
    project_id: int,
    experiment_id: int,
    req: HumanAnnotationBatch,
):
    """Submit human ratings for experiment results. Upserts (replaces existing)."""
    conn = db.init.get_db()
    _validate_experiment(conn, project_id, experiment_id)

    # Validate all experiment_result_ids belong to this experiment
    result_ids = [a.experiment_result_id for a in req.annotations]
    placeholders = ",".join("?" for _ in result_ids)
    valid_rows = conn.execute(
        f"SELECT id FROM experiment_results WHERE id IN ({placeholders}) AND experiment_id = ?",
        (*result_ids, experiment_id),
    ).fetchall()
    valid_ids = {r["id"] for r in valid_rows}

    invalid_ids = [rid for rid in result_ids if rid not in valid_ids]
    if invalid_ids:
        raise HTTPException(
            status_code=422,
            detail=f"experiment_result_ids not found in this experiment: {invalid_ids}",
        )

    # Upsert: delete existing then insert
    conn.execute(
        f"DELETE FROM human_annotations WHERE experiment_result_id IN ({placeholders})",
        result_ids,
    )

    for a in req.annotations:
        conn.execute(
            """INSERT INTO human_annotations (experiment_result_id, rating, notes)
               VALUES (?, ?, ?)""",
            (a.experiment_result_id, a.rating, a.notes),
        )

    conn.commit()

    return {
        "experiment_id": experiment_id,
        "submitted": len(req.annotations),
    }


@router.get("/projects/{project_id}/experiments/{experiment_id}/evaluator-accuracy")
async def get_evaluator_accuracy(project_id: int, experiment_id: int):
    """Compute agreement between human annotations and automated evaluator scores.

    For each annotated result, compares the human rating to the average of
    correctness-related metric scores. Returns per-result agreement and an
    overall agreement percentage.
    """
    conn = db.init.get_db()
    _validate_experiment(conn, project_id, experiment_id)

    # Fetch all annotations for this experiment
    rows = conn.execute(
        """SELECT ha.*, er.metrics_json, er.response,
                  tq.question, tq.reference_answer, tq.user_edited_answer
           FROM human_annotations ha
           JOIN experiment_results er ON ha.experiment_result_id = er.id
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY ha.experiment_result_id""",
        (experiment_id,),
    ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=409,
            detail="No annotations found. Submit annotations before computing evaluator accuracy.",
        )

    comparisons = []
    agreements = 0

    for r in rows:
        metrics = json.loads(r["metrics_json"]) if r["metrics_json"] else {}
        human_score = _RATING_SCORES[r["rating"]]

        # Compute evaluator score: average of available correctness metrics
        metric_values = []
        for m in _CORRECTNESS_METRICS:
            if m in metrics and metrics[m] is not None:
                metric_values.append(metrics[m])

        if metric_values:
            evaluator_score = sum(metric_values) / len(metric_values)
        else:
            evaluator_score = None

        # Determine agreement: both agree on the same "bucket"
        # human: accurate=1.0, partial=0.5, inaccurate=0.0
        # evaluator: >= 0.7 = accurate, 0.4-0.7 = partial, < 0.4 = inaccurate
        evaluator_rating = None
        agrees = None
        if evaluator_score is not None:
            if evaluator_score >= 0.7:
                evaluator_rating = "accurate"
            elif evaluator_score >= 0.4:
                evaluator_rating = "partially_accurate"
            else:
                evaluator_rating = "inaccurate"
            agrees = evaluator_rating == r["rating"]
            if agrees:
                agreements += 1

        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]

        comparisons.append({
            "experiment_result_id": r["experiment_result_id"],
            "question": r["question"],
            "response": r["response"],
            "reference_answer": ref_answer,
            "human_rating": r["rating"],
            "human_score": human_score,
            "evaluator_score": round(evaluator_score, 4) if evaluator_score is not None else None,
            "evaluator_rating": evaluator_rating,
            "agrees": agrees,
            "notes": r["notes"],
        })

    scorable = [c for c in comparisons if c["agrees"] is not None]
    agreement_rate = round(agreements / len(scorable), 4) if scorable else None

    return {
        "experiment_id": experiment_id,
        "total_annotations": len(comparisons),
        "scorable_count": len(scorable),
        "agreements": agreements,
        "agreement_rate": agreement_rate,
        "comparisons": comparisons,
    }
