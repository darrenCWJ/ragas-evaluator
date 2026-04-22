"""Project-level reporting: per-bot aggregates, source verification summary,
evaluator reliability, and cross-experiment trends."""

import json
import logging

from fastapi import APIRouter, HTTPException, Query

from app.routes.experiments import _sanitize_nan
import db.init

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _aggregate_metrics(result_rows: list[dict]) -> dict[str, float | None]:
    """Compute per-metric averages from a list of experiment_results rows."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rr in result_rows:
        metrics = _sanitize_nan(json.loads(rr["metrics_json"])) if rr["metrics_json"] else {}
        for name, value in metrics.items():
            if value is not None:
                totals[name] = totals.get(name, 0.0) + value
                counts[name] = counts.get(name, 0) + 1

    return {
        mn: round(totals[mn] / counts[mn], 4) if counts.get(mn, 0) > 0 else None
        for mn in totals
    }


def _overall_score(aggregate: dict[str, float | None]) -> float | None:
    valid = [v for v in aggregate.values() if v is not None]
    return round(sum(valid) / len(valid), 4) if valid else None


def _source_verification_summary(conn, experiment_id: int) -> dict | None:
    """Return verification status counts for an experiment, or None if none exist."""
    rows = conn.execute(
        """SELECT sv.status
           FROM source_verifications sv
           JOIN experiment_results er ON sv.experiment_result_id = er.id
           WHERE er.experiment_id = ?""",
        (experiment_id,),
    ).fetchall()

    if not rows:
        return None

    statuses = [r["status"] for r in rows]
    total = len(statuses)
    counts = {
        "verified": statuses.count("verified"),
        "hallucinated": statuses.count("hallucinated"),
        "inaccessible": statuses.count("inaccessible"),
        "unverifiable": statuses.count("unverifiable"),
        "total": total,
    }
    # Add percentages
    counts["pct_verified"] = round(counts["verified"] / total * 100, 1) if total else 0
    counts["pct_hallucinated"] = round(counts["hallucinated"] / total * 100, 1) if total else 0
    return counts


def _evaluator_reliability(conn, experiment_id: int) -> dict | None:
    """Compute evaluator-vs-human agreement for an experiment, or None if no annotations."""
    rows = conn.execute(
        """SELECT ha.rating, er.metrics_json
           FROM human_annotations ha
           JOIN experiment_results er ON ha.experiment_result_id = er.id
           WHERE er.experiment_id = ?""",
        (experiment_id,),
    ).fetchall()

    if not rows:
        return None

    correctness_metrics = [
        "factual_correctness", "faithfulness", "answer_relevancy", "semantic_similarity",
    ]
    agreements = 0
    scorable = 0

    for r in rows:
        metrics = _sanitize_nan(json.loads(r["metrics_json"])) if r["metrics_json"] else {}
        values = [metrics[m] for m in correctness_metrics if m in metrics and metrics[m] is not None]
        if not values:
            continue

        evaluator_score = sum(values) / len(values)
        if evaluator_score >= 0.7:
            evaluator_rating = "accurate"
        elif evaluator_score >= 0.4:
            evaluator_rating = "partially_accurate"
        else:
            evaluator_rating = "inaccurate"

        scorable += 1
        if evaluator_rating == r["rating"]:
            agreements += 1

    if scorable == 0:
        return None

    return {
        "total_annotations": len(rows),
        "scorable_count": scorable,
        "agreements": agreements,
        "agreement_rate": round(agreements / scorable, 4),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/report")
async def get_project_report(project_id: int):
    """Aggregate report across all completed experiments in a project.

    Returns per-experiment metrics, source verification summaries,
    evaluator reliability scores, and overall project-level aggregates.
    """
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiments = conn.execute(
        """SELECT * FROM experiments
           WHERE project_id = ? AND status = 'completed'
           ORDER BY completed_at DESC""",
        (project_id,),
    ).fetchall()

    if not experiments:
        return {
            "project_id": project_id,
            "project_name": project["name"],
            "total_experiments": 0,
            "experiments": [],
            "bot_summary": [],
            "overall_metrics": None,
            "overall_source_verification": None,
            "overall_evaluator_reliability": None,
        }

    exp_ids = [exp["id"] for exp in experiments]
    bc_ids = list({exp["bot_config_id"] for exp in experiments if exp["bot_config_id"]})
    rc_ids = list({exp["rag_config_id"] for exp in experiments if exp["rag_config_id"]})

    exp_placeholders = ",".join("?" * len(exp_ids))
    all_result_rows_raw = conn.execute(
        f"SELECT experiment_id, metrics_json FROM experiment_results WHERE experiment_id IN ({exp_placeholders})",
        exp_ids,
    ).fetchall()
    results_by_exp: dict[int, list] = {eid: [] for eid in exp_ids}
    for rr in all_result_rows_raw:
        results_by_exp[rr["experiment_id"]].append(rr)

    bc_info: dict[int, dict] = {}
    if bc_ids:
        bc_placeholders = ",".join("?" * len(bc_ids))
        for r in conn.execute(
            f"SELECT id, name, connector_type FROM bot_configs WHERE id IN ({bc_placeholders})",
            bc_ids,
        ).fetchall():
            bc_info[r["id"]] = {"name": r["name"], "connector_type": r["connector_type"]}

    rc_name: dict[int, str] = {}
    if rc_ids:
        rc_placeholders = ",".join("?" * len(rc_ids))
        for r in conn.execute(
            f"SELECT id, name FROM rag_configs WHERE id IN ({rc_placeholders})", rc_ids
        ).fetchall():
            rc_name[r["id"]] = r["name"]

    # Build per-experiment detail
    experiment_reports = []
    # Accumulators for project-level rollups
    all_result_rows: list[dict] = []
    all_sv_counts: dict[str, int] = {"verified": 0, "hallucinated": 0, "inaccessible": 0, "unverifiable": 0, "total": 0}
    all_annotations_total = 0
    all_annotations_scorable = 0
    all_annotations_agreements = 0

    # Per-bot accumulators
    bot_accum: dict[int, dict] = {}  # bot_config_id -> accumulator

    for exp in experiments:
        result_rows = results_by_exp[exp["id"]]
        aggregate = _aggregate_metrics(result_rows)
        overall = _overall_score(aggregate)
        sv = _source_verification_summary(conn, exp["id"])
        reliability = _evaluator_reliability(conn, exp["id"])

        bc = bc_info.get(exp["bot_config_id"]) if exp["bot_config_id"] else None
        bot_config_name = bc["name"] if bc else None
        connector_type = bc["connector_type"] if bc else None
        rag_config_name = rc_name.get(exp["rag_config_id"]) if exp["rag_config_id"] else None

        entry = {
            "id": exp["id"],
            "name": exp["name"],
            "bot_config_id": exp["bot_config_id"],
            "bot_config_name": bot_config_name,
            "rag_config_id": exp["rag_config_id"],
            "rag_config_name": rag_config_name,
            "result_count": len(result_rows),
            "completed_at": exp["completed_at"],
            "aggregate_metrics": aggregate,
            "overall_score": overall,
            "source_verification": sv,
            "evaluator_reliability": reliability,
        }
        experiment_reports.append(entry)

        # Accumulate into project-level rollups
        all_result_rows.extend(result_rows)

        if sv:
            for key in ("verified", "hallucinated", "inaccessible", "unverifiable", "total"):
                all_sv_counts[key] += sv[key]

        if reliability:
            all_annotations_total += reliability["total_annotations"]
            all_annotations_scorable += reliability["scorable_count"]
            all_annotations_agreements += reliability["agreements"]

        # Accumulate per-bot
        if exp["bot_config_id"]:
            bid = exp["bot_config_id"]
            if bid not in bot_accum:
                bot_accum[bid] = {
                    "bot_config_id": bid,
                    "bot_config_name": bot_config_name,
                    "connector_type": connector_type,
                    "experiment_count": 0,
                    "result_rows": [],
                }
            bot_accum[bid]["experiment_count"] += 1
            bot_accum[bid]["result_rows"].extend(result_rows)

    # Project-level aggregates
    overall_metrics = _aggregate_metrics(all_result_rows) if all_result_rows else None

    overall_sv = None
    if all_sv_counts["total"] > 0:
        t = all_sv_counts["total"]
        overall_sv = {
            **all_sv_counts,
            "pct_verified": round(all_sv_counts["verified"] / t * 100, 1),
            "pct_hallucinated": round(all_sv_counts["hallucinated"] / t * 100, 1),
        }

    overall_reliability = None
    if all_annotations_scorable > 0:
        overall_reliability = {
            "total_annotations": all_annotations_total,
            "scorable_count": all_annotations_scorable,
            "agreements": all_annotations_agreements,
            "agreement_rate": round(all_annotations_agreements / all_annotations_scorable, 4),
        }

    # Per-bot summary
    bot_summary = []
    for bid, acc in bot_accum.items():
        agg = _aggregate_metrics(acc["result_rows"])
        bot_summary.append({
            "bot_config_id": acc["bot_config_id"],
            "bot_config_name": acc["bot_config_name"],
            "connector_type": acc["connector_type"],
            "experiment_count": acc["experiment_count"],
            "total_results": len(acc["result_rows"]),
            "aggregate_metrics": agg,
            "overall_score": _overall_score(agg),
        })
    bot_summary.sort(key=lambda b: b["overall_score"] or 0, reverse=True)

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "total_experiments": len(experiments),
        "experiments": experiment_reports,
        "bot_summary": bot_summary,
        "overall_metrics": overall_metrics,
        "overall_source_verification": overall_sv,
        "overall_evaluator_reliability": overall_reliability,
    }


@router.get("/projects/{project_id}/report/trends")
async def get_experiment_trends(
    project_id: int,
    bot_config_id: int | None = Query(None, description="Filter to a specific bot config"),
    metric: str = Query("overall", description="Metric name or 'overall'"),
    limit: int = Query(20, ge=1, le=100, description="Max experiments to include"),
):
    """Return time-series data for a metric across completed experiments.

    Useful for plotting performance trends over time.
    """
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    query = """SELECT * FROM experiments
               WHERE project_id = ? AND status = 'completed'"""
    params: list = [project_id]

    if bot_config_id is not None:
        query += " AND bot_config_id = ?"
        params.append(bot_config_id)

    query += " ORDER BY completed_at ASC LIMIT ?"
    params.append(limit)

    experiments = conn.execute(query, params).fetchall()

    points = []
    if experiments:
        exp_ids = [exp["id"] for exp in experiments]
        placeholders = ",".join("?" * len(exp_ids))
        result_rows_all = conn.execute(
            f"SELECT experiment_id, metrics_json FROM experiment_results WHERE experiment_id IN ({placeholders})",
            exp_ids,
        ).fetchall()
        results_by_exp: dict[int, list] = {eid: [] for eid in exp_ids}
        for rr in result_rows_all:
            results_by_exp[rr["experiment_id"]].append(rr)

        for exp in experiments:
            aggregate = _aggregate_metrics(results_by_exp[exp["id"]])
            value = _overall_score(aggregate) if metric == "overall" else aggregate.get(metric)
            points.append({
                "experiment_id": exp["id"],
                "experiment_name": exp["name"],
                "completed_at": exp["completed_at"],
                "value": value,
            })

    return {
        "project_id": project_id,
        "metric": metric,
        "bot_config_id": bot_config_id,
        "points": points,
    }
