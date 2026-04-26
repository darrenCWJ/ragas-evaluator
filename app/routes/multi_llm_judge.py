"""Multi-LLM Judge routes.

Endpoints for fetching evaluator outputs, the 20% annotation sample,
submitting claim-level human annotations, and computing per-evaluator
reliability stats.

All endpoints accept an optional ?metric_name= query parameter:
  - omitted / empty → built-in multi_llm_judge (custom_metric_name IS NULL)
  - provided        → criteria_judge metric with that name
"""

from __future__ import annotations

import json
import logging
import random

from fastapi import APIRouter, HTTPException, Query

from app.models import ClaimAnnotationRequest
from db.init import get_db, NOW_SQL
from config import MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD
from evaluation.metrics.multi_llm_judge import aggregate_score, aggregate_criteria_score
from app.routes.annotations import _validate_experiment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["multi_llm_judge"])

VALID_ANNOTATION_STATUSES = {"accurate", "inaccurate", "unsure"}

# Normalise criteria verdicts → built-in labels for the frontend panel
_CRITERIA_VERDICT_MAP = {"good": "positive", "bad": "critical", "mixed": "mixed"}



def _normalize_criteria_claims(highlights: list[dict]) -> list[dict]:
    """Convert criteria judge highlights → built-in claims shape for the panel."""
    type_map = {"supporting": "praise", "contradicting": "critique", "neutral": "critique"}
    return [
        {
            "type": type_map.get(h.get("type", "neutral"), "critique"),
            "response_quote": h.get("quote", ""),
            "chunk_reference": None,
            "chunk_quote": None,
            "explanation": h.get("critique", ""),
        }
        for h in highlights
    ]


def _load_evaluations_for_result(
    conn,
    result_id: int,
    metric_name: str | None = None,
) -> list[dict]:
    """Load evaluator rows + claim annotations for a result.

    metric_name=None → built-in judge (custom_metric_name IS NULL)
    metric_name=str  → criteria judge with that metric name
    """
    is_criteria = metric_name is not None

    if is_criteria:
        eval_rows = conn.execute(
            """SELECT * FROM multi_llm_evaluations
               WHERE experiment_result_id = ? AND custom_metric_name = ?
               ORDER BY evaluator_index""",
            (result_id, metric_name),
        ).fetchall()
    else:
        eval_rows = conn.execute(
            """SELECT * FROM multi_llm_evaluations
               WHERE experiment_result_id = ? AND custom_metric_name IS NULL
               ORDER BY evaluator_index""",
            (result_id,),
        ).fetchall()

    evaluations = []
    for ev in eval_rows:
        annotation_rows = conn.execute(
            "SELECT * FROM evaluator_claim_annotations WHERE evaluation_id = ? ORDER BY claim_index",
            (ev["id"],),
        ).fetchall()
        annotations = {
            a["claim_index"]: {
                "status": a["status"],
                "comment": a["comment"],
                "annotated_at": a["annotated_at"],
            }
            for a in annotation_rows
        }

        raw_claims = json.loads(ev["claims_json"])

        # Normalise criteria judge highlights → panel-compatible claims shape
        if is_criteria:
            claims = _normalize_criteria_claims(raw_claims)
            verdict = _CRITERIA_VERDICT_MAP.get(ev["verdict"], "mixed")
        else:
            claims = raw_claims
            verdict = ev["verdict"]

        evaluations.append({
            "id": ev["id"],
            "evaluator_index": ev["evaluator_index"],
            "verdict": verdict,
            "score": ev["score"],
            "reasoning": ev["reasoning"] or None,
            "claims": claims,
            "annotations": annotations,
            "created_at": ev["created_at"],
        })
    return evaluations


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}/results/{result_id}/judge-evaluations"
)
async def get_judge_evaluations(
    project_id: int,
    experiment_id: int,
    result_id: int,
    metric_name: str | None = Query(default=None),
):
    """Return all evaluator outputs + claim annotations for a single result.

    Pass ?metric_name=<name> for a criteria_judge metric; omit for the built-in judge.
    """
    conn = get_db()
    _validate_experiment(conn, project_id, experiment_id)

    result_row = conn.execute(
        "SELECT id FROM experiment_results WHERE id = ? AND experiment_id = ?",
        (result_id, experiment_id),
    ).fetchone()
    if result_row is None:
        raise HTTPException(status_code=404, detail="Result not found")

    evaluations = _load_evaluations_for_result(conn, result_id, metric_name or None)
    return {"result_id": result_id, "evaluations": evaluations}


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}/judge-annotation-sample"
)
async def get_judge_annotation_sample(
    project_id: int,
    experiment_id: int,
    metric_name: str | None = Query(default=None),
):
    """Return a 20% random sample of results for human claim annotation.

    Deterministic (seed = experiment_id). Only results that have evaluations
    for the requested metric are included.
    """
    conn = get_db()
    _validate_experiment(conn, project_id, experiment_id)

    resolved_metric = metric_name or None

    if resolved_metric is not None:
        all_results = conn.execute(
            """SELECT DISTINCT er.id, er.test_question_id, er.response, er.metrics_json,
                      tq.question, tq.reference_answer, tq.user_edited_answer
               FROM experiment_results er
               JOIN test_questions tq ON er.test_question_id = tq.id
               JOIN multi_llm_evaluations mle ON mle.experiment_result_id = er.id
               WHERE er.experiment_id = ? AND mle.custom_metric_name = ?
               ORDER BY er.id""",
            (experiment_id, resolved_metric),
        ).fetchall()
    else:
        all_results = conn.execute(
            """SELECT DISTINCT er.id, er.test_question_id, er.response, er.metrics_json,
                      tq.question, tq.reference_answer, tq.user_edited_answer
               FROM experiment_results er
               JOIN test_questions tq ON er.test_question_id = tq.id
               JOIN multi_llm_evaluations mle ON mle.experiment_result_id = er.id
               WHERE er.experiment_id = ? AND mle.custom_metric_name IS NULL
               ORDER BY er.id""",
            (experiment_id,),
        ).fetchall()

    total = len(all_results)
    if total == 0:
        return {
            "experiment_id": experiment_id,
            "total_results": 0,
            "sample_size": 0,
            "annotated_count": 0,
            "sample": [],
        }

    sample_size = max(1, round(total * 0.2))
    rng = random.Random(experiment_id)
    sample_indices = sorted(rng.sample(range(total), min(sample_size, total)))
    sampled_rows = [all_results[i] for i in sample_indices]

    sample = []
    annotated_count = 0
    for r in sampled_rows:
        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        evaluations = _load_evaluations_for_result(conn, r["id"], resolved_metric)

        has_annotation = any(ev["annotations"] for ev in evaluations)
        if has_annotation:
            annotated_count += 1

        sample.append({
            "result_id": r["id"],
            "test_question_id": r["test_question_id"],
            "question": r["question"],
            "reference_answer": ref_answer,
            "response": r["response"],
            "evaluations": evaluations,
        })

    return {
        "experiment_id": experiment_id,
        "total_results": total,
        "sample_size": len(sampled_rows),
        "annotated_count": annotated_count,
        "sample": sample,
    }


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/results/{result_id}"
    "/judge-evaluations/{evaluation_id}/claims/{claim_index}/annotate"
)
async def annotate_judge_claim(
    project_id: int,
    experiment_id: int,
    result_id: int,
    evaluation_id: int,
    claim_index: int,
    req: ClaimAnnotationRequest,
):
    """Upsert a human annotation on a specific evaluator claim."""
    conn = get_db()
    _validate_experiment(conn, project_id, experiment_id)

    ev_row = conn.execute(
        """SELECT mle.id FROM multi_llm_evaluations mle
           JOIN experiment_results er ON mle.experiment_result_id = er.id
           WHERE mle.id = ? AND er.id = ? AND er.experiment_id = ?""",
        (evaluation_id, result_id, experiment_id),
    ).fetchone()
    if ev_row is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    claims_row = conn.execute(
        "SELECT claims_json FROM multi_llm_evaluations WHERE id = ?", (evaluation_id,)
    ).fetchone()
    claims = json.loads(claims_row["claims_json"])
    if claim_index < 0 or claim_index >= len(claims):
        raise HTTPException(status_code=422, detail=f"claim_index {claim_index} out of range")

    conn.execute(
        f"""INSERT INTO evaluator_claim_annotations (evaluation_id, claim_index, status, comment)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(evaluation_id, claim_index)
           DO UPDATE SET status = excluded.status,
                         comment = excluded.comment,
                         annotated_at = {NOW_SQL}""",
        (evaluation_id, claim_index, req.status, req.comment),
    )
    conn.commit()

    return {"evaluation_id": evaluation_id, "claim_index": claim_index, "status": req.status}


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}/judge-reliability"
)
async def get_judge_reliability(
    project_id: int,
    experiment_id: int,
    metric_name: str | None = Query(default=None),
):
    """Return per-evaluator reliability stats and the excluded evaluator set.

    Pass ?metric_name=<name> for a criteria_judge metric; omit for the built-in judge.
    """
    conn = get_db()
    _validate_experiment(conn, project_id, experiment_id)

    resolved_metric = metric_name or None

    if resolved_metric is not None:
        rows = conn.execute(
            """SELECT mle.evaluator_index, mle.score, mle.verdict,
                      eca.status AS annotation_status
               FROM multi_llm_evaluations mle
               JOIN experiment_results er ON mle.experiment_result_id = er.id
               LEFT JOIN evaluator_claim_annotations eca ON eca.evaluation_id = mle.id
               WHERE er.experiment_id = ? AND mle.custom_metric_name = ?
               ORDER BY mle.evaluator_index""",
            (experiment_id, resolved_metric),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT mle.evaluator_index, mle.score, mle.verdict,
                      eca.status AS annotation_status
               FROM multi_llm_evaluations mle
               JOIN experiment_results er ON mle.experiment_result_id = er.id
               LEFT JOIN evaluator_claim_annotations eca ON eca.evaluation_id = mle.id
               WHERE er.experiment_id = ? AND mle.custom_metric_name IS NULL
               ORDER BY mle.evaluator_index""",
            (experiment_id,),
        ).fetchall()

    if not rows:
        return {
            "experiment_id": experiment_id,
            "evaluators": [],
            "excluded_indices": [],
            "overall_reliability": None,
            "threshold": MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD,
        }

    stats: dict[int, dict] = {}
    for r in rows:
        idx = r["evaluator_index"]
        if idx not in stats:
            stats[idx] = {
                "evaluator_index": idx,
                "accurate": 0,
                "inaccurate": 0,
                "unsure": 0,
                "total_claims_annotated": 0,
                "verdict_counts": {"positive": 0, "mixed": 0, "critical": 0},
            }
        s = stats[idx]
        # Normalise criteria verdicts for verdict_counts display
        display_verdict = _CRITERIA_VERDICT_MAP.get(r["verdict"], r["verdict"])
        s["verdict_counts"][display_verdict] = s["verdict_counts"].get(display_verdict, 0) + 1
        if r["annotation_status"] == "accurate":
            s["accurate"] += 1
            s["total_claims_annotated"] += 1
        elif r["annotation_status"] == "inaccurate":
            s["inaccurate"] += 1
            s["total_claims_annotated"] += 1
        elif r["annotation_status"] == "unsure":
            s["unsure"] += 1

    evaluators = []
    excluded_indices = []

    for idx in sorted(stats):
        s = stats[idx]
        scorable = s["accurate"] + s["inaccurate"]
        reliability = round(s["accurate"] / scorable, 4) if scorable > 0 else None

        excluded = reliability is not None and reliability < MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD
        if excluded:
            excluded_indices.append(idx)

        evaluators.append({
            "evaluator_index": idx,
            "reliability": reliability,
            "accurate_claims": s["accurate"],
            "inaccurate_claims": s["inaccurate"],
            "unsure_claims": s["unsure"],
            "total_claims_annotated": s["total_claims_annotated"],
            "verdict_counts": s["verdict_counts"],
            "excluded": excluded,
        })

    annotated = [e for e in evaluators if e["reliability"] is not None]
    overall = round(sum(e["reliability"] for e in annotated) / len(annotated), 4) if annotated else None

    return {
        "experiment_id": experiment_id,
        "evaluators": evaluators,
        "excluded_indices": excluded_indices,
        "overall_reliability": overall,
        "threshold": MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD,
        "annotation_progress": {
            "annotated_evaluators": len(annotated),
            "total_evaluators": len(evaluators),
        },
    }


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}/judge-summary"
)
async def get_judge_summary(
    project_id: int,
    experiment_id: int,
    metric_name: str | None = Query(default=None),
):
    """Return per-result judge verdicts for the Q&A table in the dashboard.

    Pass ?metric_name=<name> for a criteria_judge metric; omit for the built-in judge.
    """
    conn = get_db()
    _validate_experiment(conn, project_id, experiment_id)

    resolved_metric = metric_name or None
    is_criteria = resolved_metric is not None

    reliability_resp = await get_judge_reliability(project_id, experiment_id, metric_name=metric_name)
    excluded = set(reliability_resp["excluded_indices"])

    results = conn.execute(
        """SELECT er.id, er.metrics_json,
                  tq.question, tq.reference_answer, tq.user_edited_answer, er.response
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id""",
        (experiment_id,),
    ).fetchall()

    summary = []
    for r in results:
        if is_criteria:
            eval_rows = conn.execute(
                """SELECT evaluator_index, verdict, score
                   FROM multi_llm_evaluations
                   WHERE experiment_result_id = ? AND custom_metric_name = ?
                   ORDER BY evaluator_index""",
                (r["id"], resolved_metric),
            ).fetchall()
        else:
            eval_rows = conn.execute(
                """SELECT evaluator_index, verdict, score
                   FROM multi_llm_evaluations
                   WHERE experiment_result_id = ? AND custom_metric_name IS NULL
                   ORDER BY evaluator_index""",
                (r["id"],),
            ).fetchall()

        if not eval_rows:
            continue

        # Normalise verdict labels for display
        evaluator_verdicts = {
            ev["evaluator_index"]: _CRITERIA_VERDICT_MAP.get(ev["verdict"], ev["verdict"])
            for ev in eval_rows
        }
        eval_dicts = [
            {"evaluator_index": ev["evaluator_index"], "score": ev["score"], "verdict": ev["verdict"]}
            for ev in eval_rows
        ]

        if is_criteria:
            adjusted_score = aggregate_criteria_score(eval_dicts, excluded_indices=excluded)
        else:
            adjusted_score = aggregate_score(eval_dicts, excluded_indices=excluded)

        ref = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        summary.append({
            "result_id": r["id"],
            "question": r["question"],
            "response": r["response"],
            "reference_answer": ref,
            "evaluator_verdicts": evaluator_verdicts,
            "adjusted_score": adjusted_score,
        })

    return {
        "experiment_id": experiment_id,
        "excluded_indices": list(excluded),
        "results": summary,
    }
