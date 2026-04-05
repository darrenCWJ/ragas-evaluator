"""Experiment CRUD, runner (SSE), source verification, comparison, history, delta, and export routes."""

import csv
import io
import json
import logging
import sqlite3
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
from evaluation.source_verification import verify_all_citations, VerificationResult
import db.init
from pipeline.bot_connectors.factory import create_connector
from pipeline.rag import single_shot_query, multi_step_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["experiments"])


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
    }


def _sanitize_csv_value(val: str) -> str:
    """Prevent CSV formula injection (CWE-1236) by prefixing dangerous characters."""
    if val and isinstance(val, str) and len(val) > 0 and val[0] in ("=", "+", "-", "@"):
        return "'" + val
    return val


def _compute_aggregates(conn, exp_id: int) -> dict:
    """Compute per-metric averages for a completed experiment."""
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (exp_id,),
    ).fetchall()
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rr in result_rows:
        metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
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

        cursor = conn.execute(
            """INSERT INTO experiments
               (project_id, test_set_id, name, model, bot_config_id, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (
                project_id,
                req.test_set_id,
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

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()

    experiments = []
    for row in rows:
        exp = _parse_experiment_row(row)
        q_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
            (row["test_set_id"],),
        ).fetchone()["cnt"]
        exp["approved_question_count"] = q_count
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
            "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else {},
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

    experiments = []
    for row in rows:
        exp = _parse_experiment_row(row)

        # Fetch rag_config_name
        if row["rag_config_id"]:
            rc = conn.execute(
                "SELECT name FROM rag_configs WHERE id = ?", (row["rag_config_id"],)
            ).fetchone()
            exp["rag_config_name"] = rc["name"] if rc else None
        else:
            exp["rag_config_name"] = None

        # Compute aggregate metrics and overall score
        result_rows = conn.execute(
            "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
            (row["id"],),
        ).fetchall()
        exp["result_count"] = len(result_rows)

        if result_rows:
            metric_totals: dict[str, float] = {}
            metric_counts: dict[str, int] = {}
            for rr in result_rows:
                metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
                for metric_name, value in metrics.items():
                    if value is not None:
                        metric_totals[metric_name] = metric_totals.get(metric_name, 0.0) + value
                        metric_counts[metric_name] = metric_counts.get(metric_name, 0) + 1

            aggregate: dict[str, float | None] = {}
            for mn in metric_totals:
                cnt = metric_counts[mn]
                aggregate[mn] = round(metric_totals[mn] / cnt, 4) if cnt > 0 else None

            exp["aggregate_metrics"] = aggregate

            # Overall score = average of all non-null metric averages
            valid_scores = [v for v in aggregate.values() if v is not None]
            exp["overall_score"] = (
                round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
            )
        else:
            exp["aggregate_metrics"] = None
            exp["overall_score"] = None

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
            "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else {},
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
    conn_check = db.init.get_db()
    custom_names = {
        r["name"]
        for r in conn_check.execute(
            "SELECT name FROM custom_metrics WHERE project_id = ?", (project_id,)
        ).fetchall()
    }
    valid_names = set(ALL_METRICS) | custom_names

    requested_metrics = req.metrics if req.metrics else DEFAULT_EXPERIMENT_METRICS
    selected_metrics = [m for m in requested_metrics if m in valid_names]
    if not selected_metrics:
        raise HTTPException(status_code=400, detail="No valid metrics selected")

    async def _run_generator():
        run_conn = db.init.get_db()
        run_conn.row_factory = sqlite3.Row
        completed_count = 0

        try:
            # Atomic status claim -- prevents concurrent run race condition
            cursor = run_conn.execute(
                "UPDATE experiments SET status = 'running', started_at = ? WHERE id = ? AND status IN ('pending', 'failed')",
                (datetime.utcnow().isoformat(), experiment_id),
            )
            run_conn.commit()

            if cursor.rowcount != 1:
                yield f"event: error\ndata: {json.dumps({'message': 'Experiment already claimed by another request'})}\n\n"
                return

            # Clean up partial results from prior failed run (if any)
            deleted = run_conn.execute(
                "DELETE FROM experiment_results WHERE experiment_id = ?",
                (experiment_id,),
            )
            if deleted.rowcount > 0:
                run_conn.commit()
                logger.info(
                    "Experiment %d re-run: deleted %d partial results from prior attempt",
                    experiment_id,
                    deleted.rowcount,
                )

            # Fetch approved/edited test questions
            questions = run_conn.execute(
                "SELECT * FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited') ORDER BY id",
                (experiment["test_set_id"],),
            ).fetchall()

            total = len(questions)
            yield f"event: started\ndata: {json.dumps({'experiment_id': experiment_id, 'total_questions': total, 'metrics': selected_metrics})}\n\n"

            # Load custom metrics for this project
            custom_rows = run_conn.execute(
                "SELECT * FROM custom_metrics WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            custom_configs = []
            for cr in custom_rows:
                cm_name = cr["name"]
                if cm_name in selected_metrics:
                    custom_configs.append(CustomMetricConfig(
                        name=cm_name,
                        metric_type=cr["metric_type"],
                        prompt=cr["prompt"],
                        rubrics=json.loads(cr["rubrics_json"]) if cr["rubrics_json"] else None,
                        min_score=cr["min_score"],
                        max_score=cr["max_score"],
                    ))

            # Filter selected_metrics to only built-in ones for setup_scorers
            builtin_selected = [m for m in selected_metrics if m in ALL_METRICS]

            # Setup scorers
            scorers, custom_scorers, llm = setup_scorers(builtin_selected, custom_configs)

            # Determine execution mode: external bot or internal RAG
            use_bot = experiment["bot_config_id"] is not None
            connector = None
            virtual_config = None

            if use_bot:
                bot_cfg = run_conn.execute(
                    "SELECT * FROM bot_configs WHERE id = ?",
                    (experiment["bot_config_id"],),
                ).fetchone()
                if bot_cfg is None:
                    yield f"event: error\ndata: {json.dumps({'message': 'Bot config not found'})}\n\n"
                    return
                connector = create_connector(
                    bot_cfg["connector_type"],
                    json.loads(bot_cfg["config_json"]),
                    prompt_for_sources=bool(bot_cfg["prompt_for_sources"]),
                )
            else:
                virtual_config = _build_virtual_rag_config_row(experiment, project_id)

            for i, q_row in enumerate(questions, 1):
                question_text = q_row["question"]
                qid = q_row["id"]

                try:
                    if use_bot:
                        # External bot query
                        bot_response = await connector.query(question_text)
                        generated_answer = bot_response.answer
                        citations_data = [asdict(c) for c in bot_response.citations]
                        full_context_dicts = []
                        usage_info = {
                            "source": "bot_connector",
                            "citations": citations_data,
                            "raw_response": bot_response.raw_response,
                        }
                        context_strings = []
                    else:
                        # Internal RAG query
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

                    # Get reference answer (prefer user-edited)
                    ref_answer = (
                        q_row["user_edited_answer"]
                        if q_row["user_edited_answer"]
                        else q_row["reference_answer"]
                    )

                    # Evaluate metrics
                    metrics_result = await evaluate_experiment_row(
                        scorers,
                        question_text,
                        generated_answer,
                        ref_answer,
                        context_strings,
                        custom_scorers=custom_scorers,
                        llm=llm,
                    )

                    # Store result
                    run_conn.execute(
                        """INSERT INTO experiment_results
                           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            experiment_id,
                            qid,
                            generated_answer,
                            json.dumps(full_context_dicts),
                            json.dumps(metrics_result),
                            json.dumps(usage_info),
                        ),
                    )
                    run_conn.commit()
                    completed_count += 1

                    yield f"event: progress\ndata: {json.dumps({'current': i, 'total': total, 'question_id': qid, 'question': question_text[:100]})}\n\n"

                except Exception as e:
                    # Per-question error isolation: store error row, continue
                    logger.warning(
                        "Experiment %d question %d failed: %s",
                        experiment_id,
                        qid,
                        e,
                    )
                    run_conn.execute(
                        """INSERT INTO experiment_results
                           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            experiment_id,
                            qid,
                            None,
                            "[]",
                            "{}",
                            json.dumps({"error": str(e), "question_id": qid}),
                        ),
                    )
                    run_conn.commit()
                    completed_count += 1

                    yield f"event: progress\ndata: {json.dumps({'current': i, 'total': total, 'question_id': qid, 'question': question_text[:100], 'error': str(e)})}\n\n"

            # All questions processed -- mark completed
            run_conn.execute(
                "UPDATE experiments SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), experiment_id),
            )
            run_conn.commit()

            yield f"event: completed\ndata: {json.dumps({'experiment_id': experiment_id, 'result_count': completed_count})}\n\n"

        except Exception as e:
            logger.error("Experiment %d fatal error: %s", experiment_id, e)
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        finally:
            # Cleanup guarantee: if still "running", set to "failed"
            try:
                row = run_conn.execute(
                    "SELECT status FROM experiments WHERE id = ?",
                    (experiment_id,),
                ).fetchone()
                if row and row["status"] == "running":
                    run_conn.execute(
                        "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
                        (datetime.utcnow().isoformat(), experiment_id),
                    )
                    run_conn.commit()
            except Exception:
                pass  # Best-effort cleanup

    return StreamingResponse(_run_generator(), media_type="text/event-stream")


# --- Reset ---


@router.post("/projects/{project_id}/experiments/{experiment_id}/reset")
async def reset_experiment(project_id: int, experiment_id: int):
    """Reset a failed experiment so it can be re-run. Deletes partial results."""
    conn = db.init.get_db()

    # Atomic guard: only reset if status is 'failed' and belongs to project
    cursor = conn.execute(
        "UPDATE experiments SET status = 'pending', started_at = NULL, completed_at = NULL "
        "WHERE id = ? AND project_id = ? AND status = 'failed'",
        (experiment_id, project_id),
    )
    conn.commit()

    if cursor.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Only failed experiments can be reset.",
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
        b_metrics = json.loads(b_row["metrics_json"]) if b_row and b_row["metrics_json"] else {}
        i_metrics = json.loads(i_row["metrics_json"]) if i_row and i_row["metrics_json"] else {}
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
        metrics = json.loads(r["metrics_json"]) if r["metrics_json"] else {}
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
    llm_model: str = Query("gpt-4o-mini", description="LLM model for content verification"),
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
