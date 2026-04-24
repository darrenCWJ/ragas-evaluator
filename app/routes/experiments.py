"""Experiment CRUD, runner (SSE), source verification, comparison, history, delta, and export routes."""

import asyncio
import csv
import io
import json
import logging
import math
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models import (
    ExperimentCreate,
    ExperimentRunRequest,
    DEFAULT_EXPERIMENT_METRICS,
)
from dataclasses import asdict

from evaluation.scoring import ALL_METRICS, setup_scorers, evaluate_experiment_row
from evaluation.metrics.custom_metric import CustomMetricConfig
from evaluation.metrics import multi_llm_judge as _multi_llm_judge_module
from evaluation.source_verification import verify_all_citations
import db.init
from config import BOT_QUERY_TIMEOUT, DEFAULT_EVAL_MODEL
from pipeline.bot_connectors.factory import create_connector
from app.routes.bot_configs import bot_config_returns_contexts
from app.routes.projects import _sanitize_csv_value
from pipeline.rag import single_shot_query, multi_step_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["experiments"])

# Track cancellation signals per experiment id
_cancel_events: dict[int, asyncio.Event] = {}

# Track progress for running experiments so SSE observers can reconnect
_experiment_progress: dict[int, dict] = {}
# Track background tasks so we know which experiments are truly alive
_background_tasks: dict[int, asyncio.Task] = {}


def _reap_stale_experiments(conn) -> int:
    """Mark 'running' experiments as 'failed' if no active SSE generator exists.

    An experiment is stale when its status is 'running' but there is no
    cancel event registered — meaning the SSE generator has ended (server
    restarted, connection dropped, etc.).  No time limit is applied because
    experiments with many questions can legitimately run for hours.
    """
    rows = conn.execute(
        "SELECT id FROM experiments WHERE status = 'running'"
    ).fetchall()
    reaped = 0
    now = datetime.now()
    for row in rows:
        eid = row["id"]
        if eid not in _cancel_events and eid not in _background_tasks:
            conn.execute(
                "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
                (now.isoformat(), eid),
            )
            reaped += 1
            logger.info("Reaped stale experiment %d (no active generator)", eid)
    if reaped:
        conn.commit()
    return reaped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_experiment_row(row) -> dict:
    """Convert a DB experiment row into a serialisable dict."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "test_set_id": row["test_set_id"],
        "name": row["name"],
        "model": row["model"],
        "model_params": json.loads(row["model_params_json"]) if row["model_params_json"] else None,
        "retrieval_config": json.loads(row["retrieval_config_json"]) if row["retrieval_config_json"] else None,
        "chunk_config_id": row["chunk_config_id"],
        "embedding_config_id": row["embedding_config_id"],
        "rag_config_id": row["rag_config_id"],
        "bot_config_id": row["bot_config_id"],
        "baseline_experiment_id": row["baseline_experiment_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
    }


def _build_virtual_rag_config_row(experiment_row, project_id: int) -> dict:
    """Build a dict satisfying the rag_config_row interface for RAG query functions."""
    retrieval_config = (
        json.loads(experiment_row["retrieval_config_json"])
        if experiment_row["retrieval_config_json"]
        else {}
    )
    return {
        "project_id": project_id,
        "llm_model": experiment_row["model"],
        "llm_params_json": experiment_row["model_params_json"],
        "chunk_config_id": experiment_row["chunk_config_id"],
        "embedding_config_id": experiment_row["embedding_config_id"],
        "search_type": retrieval_config.get("search_type", "dense"),
        "sparse_config_id": retrieval_config.get("sparse_config_id"),
        "alpha": retrieval_config.get("alpha"),
        "top_k": retrieval_config.get("top_k", 5),
        "system_prompt": retrieval_config.get("system_prompt"),
        "response_mode": retrieval_config.get("response_mode", "single_shot"),
        "max_steps": retrieval_config.get("max_steps", 3),
        "reranker_model": retrieval_config.get("reranker_model"),
        "reranker_top_k": retrieval_config.get("reranker_top_k"),
    }



def _sanitize_nan(obj):
    """Replace NaN/Inf floats with None so JSON serialization produces valid output."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


def _compute_aggregates(conn, exp_id: int) -> dict:
    """Compute per-metric averages for a completed experiment."""
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (exp_id,),
    ).fetchall()
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rr in result_rows:
        metrics = _sanitize_nan(json.loads(rr["metrics_json"])) if rr["metrics_json"] else {}
        for metric_name, value in metrics.items():
            if value is not None:
                totals[metric_name] = totals.get(metric_name, 0.0) + value
                counts[metric_name] = counts.get(metric_name, 0) + 1
            else:
                if metric_name not in totals:
                    totals[metric_name] = 0.0
                if metric_name not in counts:
                    counts[metric_name] = 0
    aggregate: dict[str, float | None] = {}
    for mn in totals:
        cnt = counts[mn]
        aggregate[mn] = round(totals[mn] / cnt, 4) if cnt > 0 else None
    return aggregate


def _aggregate_rows(result_rows) -> tuple[dict | None, float | None, int]:
    """Aggregate metric scores from experiment_results rows.

    Returns (aggregate_metrics, overall_score, result_count).
    Metrics with all-null values are omitted (unlike _compute_aggregates).
    """
    n = len(result_rows)
    if not result_rows:
        return None, None, 0
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rr in result_rows:
        metrics = _sanitize_nan(json.loads(rr["metrics_json"])) if rr["metrics_json"] else {}
        for metric_name, value in metrics.items():
            if value is not None:
                totals[metric_name] = totals.get(metric_name, 0.0) + value
                counts[metric_name] = counts.get(metric_name, 0) + 1
    aggregate: dict[str, float | None] = {}
    for mn in totals:
        cnt = counts[mn]
        aggregate[mn] = round(totals[mn] / cnt, 4) if cnt > 0 else None
    valid_scores = [v for v in aggregate.values() if v is not None]
    overall = round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
    return aggregate, overall, n


# RAG config fields to compare for delta
_RAG_CONFIG_DIFF_FIELDS = [
    "name",
    "embedding_config_id",
    "chunk_config_id",
    "search_type",
    "sparse_config_id",
    "alpha",
    "llm_model",
    "top_k",
    "system_prompt",
    "response_mode",
    "max_steps",
]


# ---------------------------------------------------------------------------
# Routes — "compare" and "history" MUST be registered before /{experiment_id}
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/experiments", status_code=201)
async def create_experiment(project_id: int, req: ExperimentCreate):
    conn = db.init.get_db()

    # Validate project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # --- Bot config path (external bot testing) ---
    if req.bot_config_id is not None:
        bot_config = conn.execute(
            "SELECT * FROM bot_configs WHERE id = ? AND project_id = ?",
            (req.bot_config_id, project_id),
        ).fetchone()
        if bot_config is None:
            raise HTTPException(
                status_code=422,
                detail="Bot config not found in this project",
            )

        test_set_id = req.test_set_id

        # CSV connectors: auto-create a test set from external_baselines
        if bot_config["connector_type"] == "csv" and test_set_id is None:
            baselines = conn.execute(
                "SELECT question, answer, reference_answer, sources FROM external_baselines WHERE bot_config_id = ?",
                (req.bot_config_id,),
            ).fetchall()
            if not baselines:
                raise HTTPException(
                    status_code=422,
                    detail="No baseline rows found for this CSV bot connector",
                )

            gen_config = json.dumps({
                "source": "csv_auto",
                "bot_config_id": req.bot_config_id,
                "row_count": len(baselines),
            })
            ts_cursor = conn.execute(
                "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
                (project_id, f"{bot_config['name']} (auto)", gen_config),
            )
            test_set_id = ts_cursor.lastrowid

            for bl in baselines:
                # reference_answer = ground truth; falls back to bot answer for backward compat
                ref_ans = bl["reference_answer"] if bl["reference_answer"] else bl["answer"]
                ref_ctx = json.dumps([bl["sources"]]) if bl["sources"] else "[]"
                conn.execute(
                    """INSERT INTO test_questions
                       (test_set_id, question, reference_answer, reference_contexts, question_type, status)
                       VALUES (?, ?, ?, ?, 'csv_auto', 'approved')""",
                    (test_set_id, bl["question"], ref_ans, ref_ctx),
                )
            conn.commit()
        elif test_set_id is None:
            raise HTTPException(
                status_code=422,
                detail="test_set_id is required for non-CSV bot connectors",
            )
        else:
            # Validate test_set belongs to project
            test_set = conn.execute(
                "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
                (test_set_id, project_id),
            ).fetchone()
            if test_set is None:
                raise HTTPException(
                    status_code=422,
                    detail="Test set not found in this project",
                )

        cursor = conn.execute(
            """INSERT INTO experiments
               (project_id, test_set_id, name, model, bot_config_id, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (
                project_id,
                test_set_id,
                req.name,
                f"{bot_config['connector_type']}:{bot_config['name']}",
                req.bot_config_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _parse_experiment_row(row)

    # --- RAG config path (internal RAG pipeline, legacy) ---
    if req.test_set_id is None:
        raise HTTPException(
            status_code=422,
            detail="test_set_id is required for RAG experiments",
        )

    # Validate test_set belongs to project
    test_set = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (req.test_set_id, project_id),
    ).fetchone()
    if test_set is None:
        raise HTTPException(
            status_code=422,
            detail="Test set not found in this project",
        )

    # Check that test set has approved/edited questions
    approved_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
        (req.test_set_id,),
    ).fetchone()["cnt"]
    if approved_count == 0:
        raise HTTPException(
            status_code=422,
            detail="Test set has no approved questions",
        )

    rag_config = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (req.rag_config_id, project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(
            status_code=422,
            detail="RAG config not found in this project",
        )

    # Snapshot config from rag_config for reproducibility
    retrieval_config = json.dumps({
        "search_type": rag_config["search_type"],
        "sparse_config_id": rag_config["sparse_config_id"],
        "alpha": rag_config["alpha"],
        "top_k": rag_config["top_k"],
        "system_prompt": rag_config["system_prompt"],
        "response_mode": rag_config["response_mode"],
        "max_steps": rag_config["max_steps"],
    })

    cursor = conn.execute(
        """INSERT INTO experiments
           (project_id, test_set_id, name, model, model_params_json, retrieval_config_json,
            chunk_config_id, embedding_config_id, rag_config_id, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            project_id,
            req.test_set_id,
            req.name,
            rag_config["llm_model"],
            rag_config["llm_params_json"],
            retrieval_config,
            rag_config["chunk_config_id"],
            rag_config["embedding_config_id"],
            req.rag_config_id,
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM experiments WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _parse_experiment_row(row)


@router.get("/projects/{project_id}/experiments")
async def list_experiments(project_id: int):
    conn = db.init.get_db()

    # Auto-detect and clean up stale "running" experiments
    _reap_stale_experiments(conn)

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()

    if not rows:
        return []

    ts_ids = list({row["test_set_id"] for row in rows})
    bc_ids = [row["bot_config_id"] for row in rows if row["bot_config_id"]]

    ts_placeholders = ",".join("?" * len(ts_ids))
    q_stats = conn.execute(
        f"""
        SELECT
            test_set_id,
            SUM(CASE WHEN status IN ('approved', 'edited') THEN 1 ELSE 0 END) AS approved_count,
            MAX(CASE WHEN reference_contexts IS NOT NULL
                          AND reference_contexts != '[]'
                          AND reference_contexts != '' THEN 1 ELSE 0 END) AS has_ref_ctx,
            MAX(CASE WHEN metadata_json IS NOT NULL
                          AND metadata_json LIKE '%reference_sql%' THEN 1 ELSE 0 END) AS has_ref_sql,
            MAX(CASE WHEN metadata_json IS NOT NULL
                          AND metadata_json LIKE '%reference_data%' THEN 1 ELSE 0 END) AS has_ref_data
        FROM test_questions
        WHERE test_set_id IN ({ts_placeholders})
        GROUP BY test_set_id
        """,
        ts_ids,
    ).fetchall()
    q_stats_by_ts = {r["test_set_id"]: r for r in q_stats}

    ts_names = conn.execute(
        f"SELECT id, name FROM test_sets WHERE id IN ({ts_placeholders})", ts_ids
    ).fetchall()
    ts_name_by_id = {r["id"]: r["name"] for r in ts_names}

    bc_by_id: dict = {}
    if bc_ids:
        bc_placeholders = ",".join("?" * len(bc_ids))
        bc_rows = conn.execute(
            f"SELECT id, connector_type, config_json FROM bot_configs WHERE id IN ({bc_placeholders})",
            bc_ids,
        ).fetchall()
        bc_by_id = {r["id"]: r for r in bc_rows}

    experiments = []
    for row in rows:
        exp = _parse_experiment_row(row)
        ts_id = row["test_set_id"]
        stats = q_stats_by_ts.get(ts_id)
        exp["approved_question_count"] = stats["approved_count"] if stats else 0
        exp["test_set_name"] = ts_name_by_id.get(ts_id)
        exp["has_reference_contexts"] = bool(stats and stats["has_ref_ctx"])
        exp["has_reference_sql"] = bool(stats and stats["has_ref_sql"])
        exp["has_reference_data"] = bool(stats and stats["has_ref_data"])

        bc_id = row["bot_config_id"]
        if bc_id and bc_id in bc_by_id:
            bc = bc_by_id[bc_id]
            bc_config = json.loads(bc["config_json"]) if bc["config_json"] else {}
            exp["connector_type"] = bc["connector_type"]
            exp["bot_returns_contexts"] = bot_config_returns_contexts(
                bc["connector_type"], bc_config
            )
        else:
            exp["connector_type"] = None
            exp["bot_returns_contexts"] = False
        experiments.append(exp)

    return experiments


# --- Compare (must precede /{experiment_id} routes) ---


@router.get("/projects/{project_id}/experiments/compare")
async def compare_experiments(
    project_id: int,
    ids: str = Query(..., description="Comma-separated experiment IDs (2-5)"),
):
    # Parse and validate IDs
    raw_parts = ids.split(",")
    try:
        experiment_ids = [int(p.strip()) for p in raw_parts if p.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="All experiment IDs must be numeric")

    if len(experiment_ids) < 2 or len(experiment_ids) > 5:
        raise HTTPException(status_code=400, detail="Provide between 2 and 5 experiment IDs")

    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch all experiments with parameterized IN clause
    placeholders = ",".join("?" for _ in experiment_ids)
    rows = conn.execute(
        f"SELECT * FROM experiments WHERE id IN ({placeholders}) AND project_id = ?",
        (*experiment_ids, project_id),
    ).fetchall()

    if len(rows) != len(experiment_ids):
        found_ids = {r["id"] for r in rows}
        missing = [eid for eid in experiment_ids if eid not in found_ids]
        raise HTTPException(
            status_code=404,
            detail=f"Experiments not found in this project: {missing}",
        )

    # Validate all completed
    non_completed = [r["id"] for r in rows if r["status"] != "completed"]
    if non_completed:
        raise HTTPException(
            status_code=409,
            detail=f"All experiments must be completed. Not completed: {non_completed}",
        )

    # Validate same test set
    test_set_ids = {r["test_set_id"] for r in rows}
    if len(test_set_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail="All experiments must use the same test set for comparison",
        )

    # Build experiment metadata
    experiments_meta = []
    for row in rows:
        exp = _parse_experiment_row(row)

        ts = conn.execute(
            "SELECT name FROM test_sets WHERE id = ?", (row["test_set_id"],)
        ).fetchone()
        exp["test_set_name"] = ts["name"] if ts else None

        if row["rag_config_id"]:
            rc = conn.execute(
                "SELECT name FROM rag_configs WHERE id = ?", (row["rag_config_id"],)
            ).fetchone()
            exp["rag_config_name"] = rc["name"] if rc else None
        else:
            exp["rag_config_name"] = None

        # Compute aggregate metrics
        result_rows = conn.execute(
            "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
            (row["id"],),
        ).fetchall()
        exp["result_count"] = len(result_rows)

        if result_rows:
            exp["aggregate_metrics"] = _compute_aggregates(conn, row["id"])
        else:
            exp["aggregate_metrics"] = None

        experiments_meta.append(exp)

    # Fetch all results for all experiments
    all_results = conn.execute(
        f"""SELECT er.*, tq.question, tq.reference_answer, tq.user_edited_answer,
                   tq.question_type, tq.persona
            FROM experiment_results er
            JOIN test_questions tq ON er.test_question_id = tq.id
            WHERE er.experiment_id IN ({placeholders})
            ORDER BY tq.id""",
        tuple(experiment_ids),
    ).fetchall()

    # Guard: payload size limit
    if len(all_results) > 2500:
        raise HTTPException(
            status_code=413,
            detail="Too many results for comparison. Reduce experiment count or use experiments with smaller test sets.",
        )

    # Build per-question aligned data
    questions_map: dict[int, dict] = {}
    for r in all_results:
        qid = r["test_question_id"]
        if qid not in questions_map:
            ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
            questions_map[qid] = {
                "test_question_id": qid,
                "question": r["question"],
                "reference_answer": ref_answer,
                "question_type": r["question_type"],
                "persona": r["persona"],
                "experiments": {},
            }

        questions_map[qid]["experiments"][r["experiment_id"]] = {
            "response": r["response"],
            "metrics": _sanitize_nan(json.loads(r["metrics_json"])) if r["metrics_json"] else {},
            "retrieved_contexts": json.loads(r["retrieved_contexts"]) if r["retrieved_contexts"] else [],
            "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
        }

    questions_list = sorted(questions_map.values(), key=lambda q: q["test_question_id"])
    return {"experiments": experiments_meta, "questions": questions_list}


# --- History (must precede /{experiment_id} routes) ---


@router.get("/projects/{project_id}/experiments/history")
async def get_experiment_history(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM experiments WHERE project_id = ? AND status = 'completed' ORDER BY completed_at DESC",
        (project_id,),
    ).fetchall()

    if not rows:
        return {"experiments": []}

    exp_ids = [row["id"] for row in rows]
    rc_ids = [row["rag_config_id"] for row in rows if row["rag_config_id"]]

    exp_placeholders = ",".join("?" * len(exp_ids))
    all_results = conn.execute(
        f"SELECT experiment_id, metrics_json FROM experiment_results WHERE experiment_id IN ({exp_placeholders})",
        exp_ids,
    ).fetchall()
    results_by_exp: dict[int, list] = {eid: [] for eid in exp_ids}
    for rr in all_results:
        results_by_exp[rr["experiment_id"]].append(rr)

    rc_name_by_id: dict[int, str] = {}
    if rc_ids:
        rc_placeholders = ",".join("?" * len(rc_ids))
        rc_rows = conn.execute(
            f"SELECT id, name FROM rag_configs WHERE id IN ({rc_placeholders})", rc_ids
        ).fetchall()
        rc_name_by_id = {r["id"]: r["name"] for r in rc_rows}

    experiments = []
    for row in rows:
        exp = _parse_experiment_row(row)
        exp["rag_config_name"] = rc_name_by_id.get(row["rag_config_id"])
        agg, overall, n = _aggregate_rows(results_by_exp[row["id"]])
        exp["result_count"] = n
        exp["aggregate_metrics"] = agg
        exp["overall_score"] = overall
        experiments.append(exp)

    return {"experiments": experiments}


# ---------------------------------------------------------------------------
# Routes that use /{experiment_id}
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/experiments/{experiment_id}")
async def get_experiment(project_id: int, experiment_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    exp = _parse_experiment_row(row)

    # Include test_set name and rag_config name for display
    ts = conn.execute(
        "SELECT name FROM test_sets WHERE id = ?", (row["test_set_id"],)
    ).fetchone()
    exp["test_set_name"] = ts["name"] if ts else None

    if row["rag_config_id"]:
        rc = conn.execute(
            "SELECT name FROM rag_configs WHERE id = ?", (row["rag_config_id"],)
        ).fetchone()
        exp["rag_config_name"] = rc["name"] if rc else None
    else:
        exp["rag_config_name"] = None

    # Include approved question count
    q_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
        (row["test_set_id"],),
    ).fetchone()["cnt"]
    exp["approved_question_count"] = q_count

    # Include result count and aggregate metrics
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()

    exp["result_count"] = len(result_rows)

    if result_rows:
        exp["aggregate_metrics"] = _compute_aggregates(conn, experiment_id)
    else:
        exp["aggregate_metrics"] = None

    return exp


@router.get("/projects/{project_id}/experiments/{experiment_id}/results")
async def get_experiment_results(project_id: int, experiment_id: int):
    conn = db.init.get_db()

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

    rows = conn.execute(
        """SELECT er.*, tq.question, tq.reference_answer, tq.user_edited_answer,
                  tq.question_type, tq.persona
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id""",
        (experiment_id,),
    ).fetchall()

    results = []
    for r in rows:
        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        results.append({
            "id": r["id"],
            "test_question_id": r["test_question_id"],
            "question": r["question"],
            "reference_answer": ref_answer,
            "question_type": r["question_type"],
            "persona": r["persona"],
            "response": r["response"],
            "retrieved_contexts": json.loads(r["retrieved_contexts"]) if r["retrieved_contexts"] else [],
            "metrics": _sanitize_nan(json.loads(r["metrics_json"])) if r["metrics_json"] else {},
            "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
            "created_at": r["created_at"],
        })

    return results


@router.delete("/projects/{project_id}/experiments/{experiment_id}", status_code=204)
async def delete_experiment(project_id: int, experiment_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # Nullify any experiments that reference this one as baseline
    conn.execute(
        "UPDATE experiments SET baseline_experiment_id = NULL WHERE baseline_experiment_id = ?",
        (experiment_id,),
    )
    conn.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))
    conn.commit()
    return None


# --- Model Registry ---


@router.get("/models")
async def get_models():
    from pipeline.llm import list_providers

    return list_providers()


# --- Experiment Runner (SSE) ---


@router.post("/projects/{project_id}/experiments/{experiment_id}/run")
async def run_experiment(
    project_id: int,
    experiment_id: int,
    req: ExperimentRunRequest,
):
    conn = db.init.get_db()

    # Pre-validation (non-authoritative -- atomic guard is inside generator)
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

    if experiment["status"] not in ("pending", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Experiment already {experiment['status']}. Only pending or failed experiments can be run.",
        )

    # Build set of valid metric names (built-in + custom for this project)
    all_custom_rows = conn.execute(
        "SELECT * FROM custom_metrics WHERE project_id = ?", (project_id,)
    ).fetchall()
    custom_names = {r["name"] for r in all_custom_rows}
    valid_names = set(ALL_METRICS) | custom_names

    requested_metrics = req.metrics if req.metrics else DEFAULT_EXPERIMENT_METRICS
    selected_metrics = [m for m in requested_metrics if m in valid_names]
    if not selected_metrics:
        raise HTTPException(status_code=400, detail="No valid metrics selected")

    # Atomically claim the experiment — set status to 'running' now so any
    # concurrent page load or refresh immediately sees the correct state.
    cursor = conn.execute(
        "UPDATE experiments SET status = 'running', started_at = ? WHERE id = ? AND status IN ('pending', 'failed')",
        (datetime.now().isoformat(), experiment_id),
    )
    conn.commit()
    if cursor.rowcount != 1:
        raise HTTPException(status_code=409, detail="Experiment already claimed by another request")

    # Clean up partial results from a prior failed run (if any)
    deleted = conn.execute(
        "DELETE FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    )
    if deleted.rowcount > 0:
        conn.commit()
        logger.info(
            "Experiment %d re-run: deleted %d partial results from prior attempt",
            experiment_id,
            deleted.rowcount,
        )

    # --- Launch background task ---
    cancel_event = asyncio.Event()
    _cancel_events[experiment_id] = cancel_event
    _experiment_progress[experiment_id] = {
        "phase": "starting", "current": 0, "total": 0,
        "question": "", "error": None, "result_count": 0,
        "completed_items": [], "in_flight": [], "scoring_metrics": [],
    }

    async def _run_background():
        run_conn = db.init.get_thread_db()
        completed_count = 0
        tasks: list[asyncio.Task] = []

        try:
            # Fetch approved/edited test questions
            questions = run_conn.execute(
                "SELECT * FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited') ORDER BY id",
                (experiment["test_set_id"],),
            ).fetchall()

            total = len(questions)
            _experiment_progress[experiment_id] = {
                "phase": "setup", "current": 0, "total": total,
                "question": "", "error": None, "result_count": 0,
                "completed_items": [],
                "in_flight": [],
                "in_flight_details": {},
                "setup_step": "Loading metric scorers...",
            }

            # Yield control so the SSE stream can send the setup phase
            await asyncio.sleep(0)

            # Resolve judge model assignments:
            # 1. Use request's judge_model_assignments if provided
            # 2. Otherwise fall back to project-level defaults
            judge_assignments = req.judge_model_assignments or None
            if not judge_assignments:
                proj_row = run_conn.execute(
                    "SELECT judge_model_assignments_json FROM projects WHERE id = ?",
                    (project_id,),
                ).fetchone()
                if proj_row and proj_row["judge_model_assignments_json"]:
                    judge_assignments = json.loads(proj_row["judge_model_assignments_json"])
            if not judge_assignments:
                from config import MULTI_LLM_JUDGE_MODEL_ASSIGNMENTS
                judge_assignments = MULTI_LLM_JUDGE_MODEL_ASSIGNMENTS

            # Validate judge model API key availability before starting
            judge_is_selected = (
                "multi_llm_judge" in selected_metrics
                or any(
                    cr["metric_type"] in ("criteria_judge", "reference_judge") and cr["name"] in selected_metrics
                    for cr in all_custom_rows
                )
            )
            if judge_is_selected and judge_assignments:
                from pipeline.llm import get_available_judge_models
                known_models = {m["id"]: m for m in await get_available_judge_models()}
                _PROVIDER_KEY = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GOOGLE_API_KEY", "openai": "OPENAI_API_KEY"}
                unknown, missing_key = [], []
                for mid in dict.fromkeys(judge_assignments):  # deduplicate, preserve order
                    if mid not in known_models:
                        unknown.append(mid)
                    elif not known_models[mid]["available"]:
                        provider = known_models[mid].get("provider", "unknown")
                        key_name = _PROVIDER_KEY.get(provider, f"{provider.upper()}_API_KEY")
                        missing_key.append(f"{mid} (needs {key_name})")
                errors = []
                if unknown:
                    errors.append(f"Unrecognised judge models: {', '.join(unknown)}")
                if missing_key:
                    errors.append(f"Missing API keys for judge models: {', '.join(missing_key)}")
                if errors:
                    raise HTTPException(status_code=400, detail=" | ".join(errors))

            # Load custom metrics for this project
            custom_rows = all_custom_rows
            custom_configs = []
            criteria_judge_configs = []
            reference_judge_configs = []
            for cr in custom_rows:
                cm_name = cr["name"]
                if cm_name not in selected_metrics:
                    continue
                if cr["metric_type"] == "criteria_judge":
                    refined = cr["refined_prompt"] if "refined_prompt" in cr.keys() else None
                    few_shot = json.loads(cr["few_shot_examples_json"]) if "few_shot_examples_json" in cr.keys() and cr["few_shot_examples_json"] else None
                    if refined:
                        criteria_judge_configs.append(
                            _multi_llm_judge_module.CriteriaJudgeConfig(
                                metric_name=cm_name,
                                refined_prompt=refined,
                                num_evaluators=len(judge_assignments) if judge_assignments else req.multi_llm_judge_evaluators,
                                model_assignments=judge_assignments,
                                temperature_assignments=req.judge_temperature_assignments,
                                few_shot_examples=few_shot,
                            )
                        )
                elif cr["metric_type"] == "reference_judge":
                    refined = cr["refined_prompt"] if "refined_prompt" in cr.keys() else None
                    few_shot = json.loads(cr["few_shot_examples_json"]) if "few_shot_examples_json" in cr.keys() and cr["few_shot_examples_json"] else None
                    if refined:
                        reference_judge_configs.append(
                            _multi_llm_judge_module.ReferenceJudgeConfig(
                                metric_name=cm_name,
                                refined_prompt=refined,
                                num_evaluators=len(judge_assignments) if judge_assignments else req.multi_llm_judge_evaluators,
                                model_assignments=judge_assignments,
                                temperature_assignments=req.judge_temperature_assignments,
                                few_shot_examples=few_shot,
                            )
                        )
                else:
                    custom_configs.append(CustomMetricConfig(
                        name=cm_name,
                        metric_type=cr["metric_type"],
                        prompt=cr["prompt"],
                        rubrics=json.loads(cr["rubrics_json"]) if cr["rubrics_json"] else None,
                        min_score=cr["min_score"],
                        max_score=cr["max_score"],
                    ))

            # Filter selected_metrics to only built-in ones for setup_scorers
            # multi_llm_judge, criteria_judge, and reference_judge metrics are excluded
            # from setup_scorers — handled separately below.
            criteria_names = {cfg.metric_name for cfg in criteria_judge_configs}
            reference_names = {cfg.metric_name for cfg in reference_judge_configs}
            judge_custom_names = criteria_names | reference_names
            builtin_selected = [
                m for m in selected_metrics
                if m in ALL_METRICS and m != "multi_llm_judge"
            ]

            # Setup multi-llm-judge config if selected
            judge_config = None
            if "multi_llm_judge" in selected_metrics:
                n_evaluators = len(judge_assignments) if judge_assignments else req.multi_llm_judge_evaluators
                judge_config = _multi_llm_judge_module.MultiLLMJudgeConfig(
                    num_evaluators=n_evaluators,
                    model_assignments=judge_assignments,
                    temperature_assignments=req.judge_temperature_assignments,
                )
                logger.info(
                    "Experiment %d: multi_llm_judge enabled with %d evaluators (assignments: %s)",
                    experiment_id, n_evaluators, judge_assignments,
                )

            # Setup scorers — skip entirely when no built-in or custom metrics
            # are selected (e.g. only multi_llm_judge). Calling setup_scorers([])
            # or setup_scorers(None) falls back to ALL_METRICS inside that
            # function, so we must guard the call here instead.
            logger.info("Experiment %d: setting up scorers for %s", experiment_id, builtin_selected)
            scorers, custom_scorers, llm = setup_scorers(
                builtin_selected,   # [] → no built-in metrics (fixed in scoring.py)
                custom_configs,
                rubrics=req.rubrics,
            )
            logger.info("Experiment %d: scorers ready (%d built-in, %d custom)", experiment_id, len(scorers), len(custom_scorers or {}))

            # Transition from setup → running
            _experiment_progress[experiment_id] = {
                "phase": "running", "current": 0, "total": total,
                "question": "", "error": None, "result_count": 0,
                "completed_items": [],
                "in_flight": [],
                "in_flight_details": {},
            }

            # Determine execution mode: external bot or internal RAG
            use_bot = experiment["bot_config_id"] is not None
            is_csv = False
            connector = None
            virtual_config = None
            csv_answer_lookup: dict[str, dict] = {}

            if use_bot:
                bot_cfg = run_conn.execute(
                    "SELECT * FROM bot_configs WHERE id = ?",
                    (experiment["bot_config_id"],),
                ).fetchone()
                if bot_cfg is None:
                    _experiment_progress[experiment_id] = {
                        "phase": "error", "current": 0, "total": total,
                        "question": "", "error": "Bot config not found", "result_count": 0,
                    }
                    return
                is_csv = bot_cfg["connector_type"] == "csv"
                if is_csv:
                    # Pre-load bot answers from external_baselines for direct lookup
                    bl_rows = run_conn.execute(
                        "SELECT question, answer, sources FROM external_baselines WHERE bot_config_id = ?",
                        (experiment["bot_config_id"],),
                    ).fetchall()
                    for bl in bl_rows:
                        csv_answer_lookup[bl["question"].strip().lower()] = {
                            "answer": bl["answer"],
                            "sources": bl["sources"] or "",
                        }
                else:
                    bot_config_dict = json.loads(bot_cfg["config_json"]) if bot_cfg["config_json"] else {}
                    connector = create_connector(
                        bot_cfg["connector_type"],
                        bot_config_dict,
                        prompt_for_sources=bool(bot_cfg["prompt_for_sources"]),
                    )
            else:
                virtual_config = _build_virtual_rag_config_row(experiment, project_id)

            # --- Concurrent question processing ---
            semaphore = asyncio.Semaphore(req.concurrency)
            progress_queue: asyncio.Queue = asyncio.Queue()

            async def _process_question(idx: int, q_row):
                """Process a single question under the semaphore."""
                question_text = q_row["question"]
                qid = q_row["id"]

                async with semaphore:
                    if cancel_event.is_set():
                        return  # skip if cancelled

                    # Track in-flight question with detail
                    prog = _experiment_progress.get(experiment_id)
                    if prog is not None:
                        prog["in_flight"] = [*prog["in_flight"], question_text[:120]]
                        all_metric_names = list(scorers.keys()) + list((custom_scorers or {}).keys())
                        prog["in_flight_details"][qid] = {
                            "question": question_text[:200],
                            "phase": "scoring" if is_csv else "querying",
                            "metrics_done": [],
                            "metrics_active": [],
                            "metrics_pending": all_metric_names[:],
                        }

                    try:
                        if is_csv:
                            # Look up the bot's actual answer from external_baselines;
                            # reference_answer (ground truth) comes from test_questions.
                            logger.info("CSV experiment %d: processing q%d '%s'", experiment_id, qid, question_text[:60])
                            csv_match = csv_answer_lookup.get(question_text.strip().lower())
                            if csv_match:
                                generated_answer = csv_match["answer"]
                                source_text = csv_match["sources"]
                            else:
                                generated_answer = (
                                    q_row["user_edited_answer"]
                                    if q_row["user_edited_answer"]
                                    else q_row["reference_answer"]
                                ) or ""
                                source_text = ""
                            raw_contexts = json.loads(q_row["reference_contexts"]) if q_row["reference_contexts"] else []
                            full_context_dicts = [
                                {"content": c, "source": "csv_upload"} if isinstance(c, str)
                                else c
                                for c in raw_contexts
                            ]
                            context_strings = [
                                c if isinstance(c, str) else c.get("content", "")
                                for c in raw_contexts
                            ]
                            usage_info = {"source": "csv_preloaded"}
                        elif use_bot:
                            bot_response = await asyncio.wait_for(
                                connector.query(question_text), timeout=BOT_QUERY_TIMEOUT
                            )
                            generated_answer = bot_response.answer
                            citations_data = [asdict(c) for c in bot_response.citations]

                            # Build context dicts from citations so RAGAS
                            # metrics (faithfulness, context_precision, etc.)
                            # can evaluate against the bot's retrieved sources.
                            full_context_dicts = [
                                {
                                    "content": c.snippet,
                                    "source": c.url or c.title or "unknown",
                                    "datasource": c.datasource,
                                    "container": c.container,
                                }
                                for c in bot_response.citations
                                if c.snippet
                            ]
                            citation_contexts = [d["content"] for d in full_context_dicts]

                            usage_info = {
                                "source": "bot_connector",
                                "citations": citations_data,
                                "raw_response": bot_response.raw_response,
                            }
                            # Use the bot's actual retrieved contexts for
                            # scoring — these are what RAGAS metrics should
                            # evaluate (retrieval quality, faithfulness, etc.).
                            context_strings = citation_contexts
                        else:
                            response_mode = virtual_config["response_mode"]
                            if response_mode == "multi_step":
                                query_result = await multi_step_query(
                                    question_text, virtual_config, run_conn
                                )
                            else:
                                query_result = await single_shot_query(
                                    question_text, virtual_config, run_conn
                                )
                            generated_answer = query_result["answer"]
                            full_context_dicts = query_result["contexts"]
                            usage_info = query_result.get("usage", {})
                            context_strings = [c["content"] for c in full_context_dicts]

                        # Update phase to scoring
                        prog = _experiment_progress.get(experiment_id)
                        if prog is not None and qid in prog["in_flight_details"]:
                            prog["in_flight_details"][qid]["phase"] = "scoring"

                        ref_answer = (
                            q_row["user_edited_answer"]
                            if q_row["user_edited_answer"]
                            else q_row["reference_answer"]
                        )
                        q_metadata = json.loads(q_row["metadata_json"]) if q_row["metadata_json"] else None

                        def _on_metric_start(metric_name):
                            prog = _experiment_progress.get(experiment_id)
                            if prog is not None:
                                active = set(prog.get("scoring_metrics", []))
                                active.add(metric_name)
                                prog["scoring_metrics"] = sorted(active)
                                # Per-question tracking
                                detail = prog.get("in_flight_details", {}).get(qid)
                                if detail is not None:
                                    if metric_name in detail["metrics_pending"]:
                                        detail["metrics_pending"] = [m for m in detail["metrics_pending"] if m != metric_name]
                                    if metric_name not in detail["metrics_active"]:
                                        detail["metrics_active"] = [*detail["metrics_active"], metric_name]

                        def _on_metric_done(metric_name):
                            prog = _experiment_progress.get(experiment_id)
                            if prog is not None:
                                active = set(prog.get("scoring_metrics", []))
                                active.discard(metric_name)
                                prog["scoring_metrics"] = sorted(active)
                                # Per-question tracking
                                detail = prog.get("in_flight_details", {}).get(qid)
                                if detail is not None:
                                    detail["metrics_active"] = [m for m in detail["metrics_active"] if m != metric_name]
                                    if metric_name not in detail["metrics_done"]:
                                        detail["metrics_done"] = [*detail["metrics_done"], metric_name]

                        metrics_result = await evaluate_experiment_row(
                            scorers,
                            question_text,
                            generated_answer,
                            ref_answer,
                            context_strings,
                            custom_scorers=custom_scorers,
                            llm=llm,
                            on_metric_start=_on_metric_start,
                            on_metric_done=_on_metric_done,
                            rubrics=req.rubrics,
                            metadata=q_metadata,
                        )

                        await progress_queue.put({
                            "idx": idx, "qid": qid, "question_text": question_text,
                            "generated_answer": generated_answer,
                            "reference_answer": ref_answer,
                            "full_context_dicts": full_context_dicts,
                            "metrics_result": metrics_result,
                            "usage_info": usage_info,
                            "error": None,
                        })

                    except Exception as e:
                        logger.warning("Experiment %d question %d failed: %s", experiment_id, qid, e)
                        await progress_queue.put({
                            "idx": idx, "qid": qid, "question_text": question_text,
                            "generated_answer": None,
                            "full_context_dicts": [],
                            "metrics_result": {},
                            "usage_info": {"error": str(e), "question_id": qid},
                            "error": str(e),
                        })

            # Launch all question tasks concurrently (semaphore limits actual parallelism)
            tasks = [
                asyncio.create_task(_process_question(i, q_row))
                for i, q_row in enumerate(questions, 1)
            ]

            # Collect results as they complete
            finished = 0
            while finished < total:
                if cancel_event.is_set():
                    break
                try:
                    result = await asyncio.wait_for(progress_queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                finished += 1
                qid = result["qid"]
                question_text = result["question_text"]

                if result["error"] is None:
                    run_conn = db.init.reconnect_if_needed(run_conn)
                    cur = run_conn.execute(
                        """INSERT INTO experiment_results
                           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            experiment_id, qid,
                            result["generated_answer"],
                            json.dumps(result["full_context_dicts"]),
                            json.dumps(_sanitize_nan(result["metrics_result"])),
                            json.dumps(result["usage_info"]),
                        ),
                    )
                    result_row_id = cur.lastrowid

                    # --- Multi-LLM Judge (isolated block — no impact on normal metrics) ---
                    if judge_config is not None:
                        try:
                            judge_evals = await _multi_llm_judge_module.run_judge(
                                judge_config,
                                result["question_text"],
                                result["generated_answer"] or "",
                                result["full_context_dicts"],
                            )
                            if judge_evals:
                                for ev in judge_evals:
                                    run_conn.execute(
                                        """INSERT INTO multi_llm_evaluations
                                           (experiment_result_id, evaluator_index, verdict, score, claims_json, reasoning)
                                           VALUES (?, ?, ?, ?, ?, ?)""",
                                        (
                                            result_row_id,
                                            ev["evaluator_index"],
                                            ev["verdict"],
                                            ev["score"],
                                            json.dumps(ev["claims"]),
                                            ev.get("reasoning") or None,
                                        ),
                                    )
                                agg = _multi_llm_judge_module.aggregate_score(judge_evals)
                                result["metrics_result"]["multi_llm_judge"] = agg
                                run_conn.execute(
                                    "UPDATE experiment_results SET metrics_json = ? WHERE id = ?",
                                    (json.dumps(_sanitize_nan(result["metrics_result"])), result_row_id),
                                )
                        except Exception as _judge_err:
                            logger.warning(
                                "Experiment %d: multi_llm_judge failed for result %d: %s",
                                experiment_id, result_row_id, _judge_err,
                                exc_info=True,
                            )
                    # --- End Multi-LLM Judge block ---

                    # --- Criteria Judges (one per custom criteria_judge metric) ---
                    for cj_config in criteria_judge_configs:
                        try:
                            cj_evals = await _multi_llm_judge_module.run_criteria_judge(
                                cj_config,
                                result["question_text"],
                                result["generated_answer"] or "",
                                result["full_context_dicts"],
                            )
                            if cj_evals:
                                for ev in cj_evals:
                                    run_conn.execute(
                                        """INSERT INTO multi_llm_evaluations
                                           (experiment_result_id, evaluator_index, verdict, score,
                                            claims_json, custom_metric_name)
                                           VALUES (?, ?, ?, ?, ?, ?)""",
                                        (
                                            result_row_id,
                                            ev["evaluator_index"],
                                            ev["verdict"],
                                            ev["score"],
                                            json.dumps(ev["highlights"]),
                                            cj_config.metric_name,
                                        ),
                                    )
                                agg = _multi_llm_judge_module.aggregate_criteria_score(cj_evals)
                                result["metrics_result"][cj_config.metric_name] = agg
                                run_conn.execute(
                                    "UPDATE experiment_results SET metrics_json = ? WHERE id = ?",
                                    (json.dumps(_sanitize_nan(result["metrics_result"])), result_row_id),
                                )
                        except Exception as _cj_err:
                            logger.warning(
                                "Experiment %d: criteria_judge '%s' failed for result %d: %s",
                                experiment_id, cj_config.metric_name, result_row_id, _cj_err,
                                exc_info=True,
                            )
                    # --- End Criteria Judges block ---

                    # --- Reference Judges (one per custom reference_judge metric) ---
                    for rj_config in reference_judge_configs:
                        try:
                            rj_evals = await _multi_llm_judge_module.run_reference_judge(
                                rj_config,
                                result["question_text"],
                                result["reference_answer"] or "",
                                result["generated_answer"] or "",
                                result["full_context_dicts"],
                            )
                            if rj_evals:
                                for ev in rj_evals:
                                    run_conn.execute(
                                        """INSERT INTO multi_llm_evaluations
                                           (experiment_result_id, evaluator_index, verdict, score,
                                            claims_json, custom_metric_name)
                                           VALUES (?, ?, ?, ?, ?, ?)""",
                                        (
                                            result_row_id,
                                            ev["evaluator_index"],
                                            ev["verdict"],
                                            ev["score"],
                                            json.dumps(ev["highlights"]),
                                            rj_config.metric_name,
                                        ),
                                    )
                                agg = _multi_llm_judge_module.aggregate_criteria_score(rj_evals)
                                result["metrics_result"][rj_config.metric_name] = agg
                                run_conn.execute(
                                    "UPDATE experiment_results SET metrics_json = ? WHERE id = ?",
                                    (json.dumps(_sanitize_nan(result["metrics_result"])), result_row_id),
                                )
                        except Exception as _rj_err:
                            logger.warning(
                                "Experiment %d: reference_judge '%s' failed for result %d: %s",
                                experiment_id, rj_config.metric_name, result_row_id, _rj_err,
                                exc_info=True,
                            )
                    # --- End Reference Judges block ---
                else:
                    run_conn.execute(
                        """INSERT INTO experiment_results
                           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (experiment_id, qid, None, "[]", "{}", json.dumps(result["usage_info"])),
                    )
                run_conn.commit()
                completed_count += 1

                # Update shared progress state (preserve accumulated lists)
                prog = _experiment_progress.get(experiment_id, {})
                completed_items = prog.get("completed_items", [])
                in_flight = prog.get("in_flight", [])

                # Add to completed log (keep last 50 to bound memory)
                completed_items = [*completed_items[-49:], {
                    "question": question_text[:200],
                    "response": (result["generated_answer"] or "")[:300] if result["generated_answer"] else None,
                    "error": result["error"],
                    "metrics": result["metrics_result"] if result["error"] is None else {},
                }]

                # Remove from in-flight
                q_short = question_text[:120]
                in_flight = [q for q in in_flight if q != q_short]

                # Remove from in_flight_details
                in_flight_details = dict(prog.get("in_flight_details", {}))
                in_flight_details.pop(qid, None)

                _experiment_progress[experiment_id] = {
                    "phase": "running", "current": finished, "total": total,
                    "question": question_text[:100],
                    "error": result["error"],
                    "result_count": completed_count,
                    "completed_items": completed_items,
                    "in_flight": in_flight,
                    "in_flight_details": in_flight_details,
                    "scoring_metrics": prog.get("scoring_metrics", []),
                }

            # Cancel pending tasks immediately if we broke out early
            if cancel_event.is_set():
                for t in tasks:
                    if not t.done():
                        t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            if cancel_event.is_set():
                run_conn.execute(
                    "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), experiment_id),
                )
                run_conn.commit()
                _experiment_progress[experiment_id] = {
                    "phase": "cancelled", "current": finished, "total": total,
                    "question": "", "error": None, "result_count": completed_count,
                }
            else:
                # All questions processed -- mark completed
                run_conn.execute(
                    "UPDATE experiments SET status = 'completed', completed_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), experiment_id),
                )
                run_conn.commit()
                _experiment_progress[experiment_id] = {
                    "phase": "completed", "current": finished, "total": total,
                    "question": "", "error": None, "result_count": completed_count,
                }

        except Exception as e:
            import traceback
            logger.error("Experiment %d fatal error: %s\n%s", experiment_id, e, traceback.format_exc())
            _experiment_progress[experiment_id] = {
                "phase": "error", "current": 0, "total": 0,
                "question": "", "error": str(e), "result_count": 0,
            }

        finally:
            _cancel_events.pop(experiment_id, None)
            _background_tasks.pop(experiment_id, None)
            # Cancel any in-flight question tasks to avoid zombie coroutines
            for t in tasks:
                if not t.done():
                    t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Cleanup guarantee: if still "running", set to "failed"
            try:
                row = run_conn.execute(
                    "SELECT status FROM experiments WHERE id = ?",
                    (experiment_id,),
                ).fetchone()
                if row and row["status"] == "running":
                    run_conn.execute(
                        "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
                        (datetime.now().isoformat(), experiment_id),
                    )
                    run_conn.commit()
            except Exception as _cleanup_err:
                logger.warning(
                    "Experiment %d: cleanup status-update failed: %s",
                    experiment_id, _cleanup_err,
                )
            finally:
                run_conn.close()

    task = asyncio.create_task(_run_background())
    _background_tasks[experiment_id] = task

    # Return JSON immediately — the frontend should use GET /progress to observe
    return {
        "experiment_id": experiment_id,
        "status": "started",
        "metrics": selected_metrics,
    }


# --- Progress snapshot (one-shot REST, for reconnect pre-population) ---


@router.get("/projects/{project_id}/experiments/{experiment_id}/progress-snapshot")
async def experiment_progress_snapshot(project_id: int, experiment_id: int):
    """Return a one-shot JSON snapshot of current in-memory progress.

    Used by the frontend on reconnect to immediately populate the UI before
    the SSE stream sends its first event, avoiding the 'Initializing...' flicker.
    """
    progress = _experiment_progress.get(experiment_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="No active progress for this experiment")
    return {
        "phase": progress.get("phase", "starting"),
        "current": progress.get("current", 0),
        "total": progress.get("total", 0),
        "question": progress.get("question", ""),
        "in_flight": progress.get("in_flight", []),
        "in_flight_details": list(progress.get("in_flight_details", {}).values()),
        "scoring_metrics": progress.get("scoring_metrics", []),
        "error": progress.get("error"),
        "result_count": progress.get("result_count", 0),
    }


# --- Progress observer (reconnectable SSE) ---


@router.get("/projects/{project_id}/experiments/{experiment_id}/progress")
async def experiment_progress(project_id: int, experiment_id: int):
    """SSE stream that observes a running experiment's progress.

    This is separate from /run so that the frontend can navigate away and
    reconnect later without affecting the background task.
    """
    progress = _experiment_progress.get(experiment_id)
    if progress is None:
        # Check if the experiment is actually running (e.g. server restarted)
        conn = db.init.get_db()
        exp = conn.execute(
            "SELECT status FROM experiments WHERE id = ? AND project_id = ?",
            (experiment_id, project_id),
        ).fetchone()
        if exp is None:
            raise HTTPException(status_code=404, detail="Experiment not found")
        if exp["status"] != "running":
            raise HTTPException(status_code=409, detail=f"Experiment is {exp['status']}, not running")
        raise HTTPException(status_code=409, detail="No active task found for this experiment")

    # Fetch experiment metadata for the started event
    obs_conn = db.init.get_db()
    obs_meta = obs_conn.execute(
        "SELECT e.name as exp_name, e.model, ts.name as test_set_name "
        "FROM experiments e JOIN test_sets ts ON e.test_set_id = ts.id WHERE e.id = ?",
        (experiment_id,),
    ).fetchone()
    obs_exp_name = obs_meta["exp_name"] if obs_meta else ""
    obs_model = obs_meta["model"] if obs_meta else ""
    obs_test_set = obs_meta["test_set_name"] if obs_meta else ""

    async def _observe():
        prev_current = -1
        prev_items_sent = 0
        sent_started = False
        while True:
            prog = _experiment_progress.get(experiment_id)
            if prog is None:
                break

            phase = prog["phase"]

            if phase == "starting":
                await asyncio.sleep(0.5)
                continue

            if phase == "setup":
                if not sent_started and prog["total"] > 0:
                    sent_started = True
                    yield f"event: started\ndata: {json.dumps({'experiment_id': experiment_id, 'total_questions': prog['total'], 'metrics': [], 'experiment_name': obs_exp_name, 'model': obs_model, 'test_set_name': obs_test_set})}\n\n"
                yield f"event: progress\ndata: {json.dumps({'current': 0, 'total': prog['total'], 'question': prog.get('setup_step', 'Setting up...'), 'error': None, 'in_flight': [], 'new_completions': [], 'scoring_metrics': [], 'in_flight_details': []})}\n\n"
                await asyncio.sleep(0.5)
                continue

            if phase == "running":
                if not sent_started and prog["total"] > 0:
                    sent_started = True
                    yield f"event: started\ndata: {json.dumps({'experiment_id': experiment_id, 'total_questions': prog['total'], 'metrics': [], 'experiment_name': obs_exp_name, 'model': obs_model, 'test_set_name': obs_test_set})}\n\n"

                completed_items = prog.get("completed_items", [])
                new_items = completed_items[prev_items_sent:]
                prev_items_sent = len(completed_items)

                details_list = list(prog.get("in_flight_details", {}).values())

                yield f"event: progress\ndata: {json.dumps({'current': prog['current'], 'total': prog['total'], 'question': prog['question'], 'error': prog.get('error'), 'in_flight': prog.get('in_flight', []), 'new_completions': new_items, 'scoring_metrics': prog.get('scoring_metrics', []), 'in_flight_details': details_list})}\n\n"
                await asyncio.sleep(0.5)
                continue

            if phase == "completed":
                yield f"event: completed\ndata: {json.dumps({'experiment_id': experiment_id, 'result_count': prog['result_count']})}\n\n"
                break

            if phase == "cancelled":
                yield f"event: cancelled\ndata: {json.dumps({'experiment_id': experiment_id, 'completed': prog['result_count']})}\n\n"
                break

            if phase == "error":
                yield f"event: error\ndata: {json.dumps({'message': prog.get('error', 'Unknown error')})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(_observe(), media_type="text/event-stream")


# --- Reset ---


@router.post("/projects/{project_id}/experiments/{experiment_id}/reset")
async def reset_experiment(project_id: int, experiment_id: int):
    """Reset a failed or completed experiment so it can be re-run. Deletes existing results."""
    conn = db.init.get_db()

    # Atomic guard: only reset if status is 'failed', 'completed', or 'running' (stuck) and belongs to project
    cursor = conn.execute(
        "UPDATE experiments SET status = 'pending', started_at = NULL, completed_at = NULL "
        "WHERE id = ? AND project_id = ? AND status IN ('failed', 'completed', 'running')",
        (experiment_id, project_id),
    )
    conn.commit()

    if cursor.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Only failed, completed, or running experiments can be reset.",
        )

    # Delete partial results
    deleted = conn.execute(
        "DELETE FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    )
    conn.commit()
    logger.info(
        "Experiment %d reset: deleted %d partial results",
        experiment_id,
        deleted.rowcount,
    )

    # Return updated experiment
    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
    ).fetchone()

    return {
        "id": experiment["id"],
        "project_id": experiment["project_id"],
        "test_set_id": experiment["test_set_id"],
        "rag_config_id": experiment["rag_config_id"],
        "name": experiment["name"],
        "model": experiment["model"],
        "status": experiment["status"],
        "created_at": experiment["created_at"],
        "started_at": experiment["started_at"],
        "completed_at": experiment["completed_at"],
    }


# --- Cancel ---


@router.post("/projects/{project_id}/experiments/{experiment_id}/cancel")
async def cancel_experiment(project_id: int, experiment_id: int):
    """Signal a running experiment to stop. Already-completed results are kept."""
    conn = db.init.get_db()
    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if experiment["status"] != "running":
        raise HTTPException(status_code=409, detail="Experiment is not running")

    event = _cancel_events.get(experiment_id)
    if event:
        event.set()
    else:
        # No event means the SSE generator already finished; force status update
        conn.execute(
            "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), experiment_id),
        )
        conn.commit()

    return {"status": "cancelling", "experiment_id": experiment_id}


# --- Delta ---


@router.get("/projects/{project_id}/experiments/{experiment_id}/delta")
async def get_experiment_delta(project_id: int, experiment_id: int):
    conn = db.init.get_db()

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

    if experiment["baseline_experiment_id"] is None:
        raise HTTPException(
            status_code=404,
            detail="No baseline experiment -- this experiment is not an iteration",
        )

    baseline = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment["baseline_experiment_id"], project_id),
    ).fetchone()
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline experiment not found")

    # Validate same test set
    if experiment["test_set_id"] != baseline["test_set_id"]:
        raise HTTPException(
            status_code=409,
            detail="Baseline and iteration experiments use different test sets -- delta comparison requires the same test set",
        )

    # Validate both completed
    if experiment["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Iteration experiment status is '{experiment['status']}', must be 'completed'",
        )
    if baseline["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Baseline experiment status is '{baseline['status']}', must be 'completed'",
        )

    # Compare RAG configs
    config_changes: list[dict] = []
    iter_config = None
    base_config = None
    if experiment["rag_config_id"]:
        iter_config = conn.execute(
            "SELECT * FROM rag_configs WHERE id = ?",
            (experiment["rag_config_id"],),
        ).fetchone()
    if baseline["rag_config_id"]:
        base_config = conn.execute(
            "SELECT * FROM rag_configs WHERE id = ?",
            (baseline["rag_config_id"],),
        ).fetchone()

    if iter_config and base_config:
        for field in _RAG_CONFIG_DIFF_FIELDS:
            old_val = base_config[field]
            new_val = iter_config[field]
            # Handle llm_params_json specially
            if field == "llm_params_json":
                old_val = json.loads(old_val) if old_val else None
                new_val = json.loads(new_val) if new_val else None
            if old_val != new_val:
                config_changes.append({
                    "field": field,
                    "old_value": old_val,
                    "new_value": new_val,
                })

    # Compute aggregate metric deltas
    baseline_agg = _compute_aggregates(conn, baseline["id"])
    iteration_agg = _compute_aggregates(conn, experiment["id"])

    all_metric_names = set(baseline_agg.keys()) | set(iteration_agg.keys())
    metric_deltas: dict[str, dict] = {}
    for mn in sorted(all_metric_names):
        b_val = baseline_agg.get(mn)
        i_val = iteration_agg.get(mn)
        delta = None
        improved = None
        if b_val is not None and i_val is not None:
            delta = round(i_val - b_val, 4)
            improved = delta > 0
        metric_deltas[mn] = {
            "baseline": b_val,
            "iteration": i_val,
            "delta": delta,
            "improved": improved,
        }

    # Per-question deltas (aligned by test_question_id)
    baseline_results = conn.execute(
        """SELECT er.test_question_id, er.metrics_json, tq.question
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?""",
        (baseline["id"],),
    ).fetchall()
    iteration_results = conn.execute(
        """SELECT er.test_question_id, er.metrics_json
           FROM experiment_results er
           WHERE er.experiment_id = ?""",
        (experiment["id"],),
    ).fetchall()

    baseline_by_q = {r["test_question_id"]: r for r in baseline_results}
    iteration_by_q = {r["test_question_id"]: r for r in iteration_results}

    all_q_ids = sorted(set(baseline_by_q.keys()) | set(iteration_by_q.keys()))
    per_question_deltas: list[dict] = []
    for qid in all_q_ids:
        b_row = baseline_by_q.get(qid)
        i_row = iteration_by_q.get(qid)
        b_metrics = _sanitize_nan(json.loads(b_row["metrics_json"])) if b_row and b_row["metrics_json"] else {}
        i_metrics = _sanitize_nan(json.loads(i_row["metrics_json"])) if i_row and i_row["metrics_json"] else {}
        question_text = b_row["question"] if b_row else None

        q_metrics: dict[str, dict] = {}
        for mn in sorted(set(b_metrics.keys()) | set(i_metrics.keys())):
            bv = b_metrics.get(mn)
            iv = i_metrics.get(mn)
            d = round(iv - bv, 4) if bv is not None and iv is not None else None
            q_metrics[mn] = {"baseline": bv, "iteration": iv, "delta": d}

        per_question_deltas.append({
            "test_question_id": qid,
            "question": question_text,
            "metrics": q_metrics,
        })

    return {
        "experiment_id": experiment["id"],
        "experiment_name": experiment["name"],
        "baseline_experiment_id": baseline["id"],
        "baseline_experiment_name": baseline["name"],
        "config_changes": config_changes,
        "metric_deltas": metric_deltas,
        "per_question_deltas": per_question_deltas,
    }


# --- Export ---


@router.get("/projects/{project_id}/experiments/{experiment_id}/export")
async def export_experiment(
    project_id: int,
    experiment_id: int,
    format: str = Query("json", description="Export format: csv or json"),
):
    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")

    conn = db.init.get_db()

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
            detail=f"Experiment status is '{experiment['status']}', must be 'completed' to export",
        )

    # Fetch results
    rows = conn.execute(
        """SELECT er.*, tq.question, tq.reference_answer, tq.user_edited_answer
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id""",
        (experiment_id,),
    ).fetchall()

    # Payload guard
    if len(rows) > 2500:
        raise HTTPException(
            status_code=413, detail="Too many results to export (max 2500)"
        )

    # Fetch RAG config name for metadata
    rag_config_name = None
    if experiment["rag_config_id"]:
        rc = conn.execute(
            "SELECT name FROM rag_configs WHERE id = ?",
            (experiment["rag_config_id"],),
        ).fetchone()
        rag_config_name = rc["name"] if rc else None

    # Collect all metric names across all results
    all_metric_names: set[str] = set()
    parsed_rows: list[dict] = []
    for r in rows:
        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        metrics = _sanitize_nan(json.loads(r["metrics_json"])) if r["metrics_json"] else {}
        all_metric_names.update(metrics.keys())
        parsed_rows.append({
            "question": r["question"],
            "reference_answer": ref_answer,
            "response": r["response"],
            "metrics": metrics,
        })

    sorted_metrics = sorted(all_metric_names)

    # Build filename
    safe_name = experiment["name"].replace(" ", "_").replace("/", "_")[:50]
    date_str = (experiment["completed_at"] or experiment["created_at"] or "")[:10]

    if format == "json":
        export_data = []
        for pr in parsed_rows:
            row_data: dict = {
                "question": pr["question"],
                "reference_answer": pr["reference_answer"],
                "response": pr["response"],
            }
            for mn in sorted_metrics:
                row_data[mn] = pr["metrics"].get(mn)
            row_data["experiment_name"] = experiment["name"]
            row_data["model"] = experiment["model"]
            row_data["rag_config"] = rag_config_name
            export_data.append(row_data)

        content = json.dumps(export_data, indent=2)
        filename = f"{safe_name}_{date_str}.json"
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV export
    output = io.StringIO()
    fieldnames = (
        ["question", "reference_answer", "response"]
        + sorted_metrics
        + ["experiment_name", "model", "rag_config"]
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for pr in parsed_rows:
        row_data = {
            "question": _sanitize_csv_value(pr["question"]),
            "reference_answer": _sanitize_csv_value(pr["reference_answer"]),
            "response": _sanitize_csv_value(pr["response"]),
        }
        for mn in sorted_metrics:
            row_data[mn] = pr["metrics"].get(mn)
        row_data["experiment_name"] = _sanitize_csv_value(experiment["name"])
        row_data["model"] = experiment["model"]
        row_data["rag_config"] = _sanitize_csv_value(rag_config_name or "")
        writer.writerow(row_data)

    csv_content = output.getvalue()
    filename = f"{safe_name}_{date_str}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Source Verification ---


@router.post("/projects/{project_id}/experiments/{experiment_id}/verify-sources")
async def verify_experiment_sources(
    project_id: int,
    experiment_id: int,
    llm_model: str = Query(DEFAULT_EVAL_MODEL, description="LLM model for content verification"),
):
    """Run source verification on all citations in a bot-connector experiment.

    Checks each citation URL for reachability and uses an LLM to verify
    whether the page content supports the bot's answer.  Results are stored
    in the source_verifications table (existing rows for this experiment are
    replaced).
    """
    conn = db.init.get_db()

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["bot_config_id"] is None:
        raise HTTPException(
            status_code=409,
            detail="Source verification is only available for bot-connector experiments",
        )

    if experiment["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be completed (current: {experiment['status']})",
        )

    # Fetch all results with citations in metadata_json
    result_rows = conn.execute(
        "SELECT id, response, metadata_json FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()

    # Clear previous verification results for this experiment
    result_ids = [r["id"] for r in result_rows]
    if result_ids:
        placeholders = ",".join("?" for _ in result_ids)
        conn.execute(
            f"DELETE FROM source_verifications WHERE experiment_result_id IN ({placeholders})",
            result_ids,
        )
        conn.commit()

    total_verified = 0
    summary: dict[str, int] = {"verified": 0, "hallucinated": 0, "inaccessible": 0, "unverifiable": 0}

    for result_row in result_rows:
        metadata = json.loads(result_row["metadata_json"]) if result_row["metadata_json"] else {}
        citations = metadata.get("citations", [])
        answer = result_row["response"] or ""

        if not citations:
            continue

        verifications = await verify_all_citations(citations, answer, llm_model)

        for v in verifications:
            conn.execute(
                """INSERT INTO source_verifications
                   (experiment_result_id, citation_index, title, url, status, details)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    result_row["id"],
                    v.citation_index,
                    v.title,
                    v.url,
                    v.status,
                    v.details,
                ),
            )
            summary[v.status] = summary.get(v.status, 0) + 1
            total_verified += 1

        conn.commit()

    return {
        "experiment_id": experiment_id,
        "total_citations_checked": total_verified,
        "summary": summary,
    }


@router.get("/projects/{project_id}/experiments/{experiment_id}/source-verifications")
async def get_source_verifications(project_id: int, experiment_id: int):
    """Return all source verification results for an experiment, grouped by result."""
    conn = db.init.get_db()

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    rows = conn.execute(
        """SELECT sv.*, er.test_question_id, tq.question
           FROM source_verifications sv
           JOIN experiment_results er ON sv.experiment_result_id = er.id
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id, sv.citation_index""",
        (experiment_id,),
    ).fetchall()

    # Group by experiment_result_id
    grouped: dict[int, dict] = {}
    for r in rows:
        rid = r["experiment_result_id"]
        if rid not in grouped:
            grouped[rid] = {
                "experiment_result_id": rid,
                "test_question_id": r["test_question_id"],
                "question": r["question"],
                "verifications": [],
            }
        grouped[rid]["verifications"].append({
            "id": r["id"],
            "citation_index": r["citation_index"],
            "title": r["title"],
            "url": r["url"],
            "status": r["status"],
            "details": r["details"],
            "created_at": r["created_at"],
        })

    # Summary counts
    all_statuses = [r["status"] for r in rows]
    summary = {
        "verified": all_statuses.count("verified"),
        "hallucinated": all_statuses.count("hallucinated"),
        "inaccessible": all_statuses.count("inaccessible"),
        "unverifiable": all_statuses.count("unverifiable"),
        "total": len(all_statuses),
    }

    return {
        "experiment_id": experiment_id,
        "summary": summary,
        "results": list(grouped.values()),
    }
