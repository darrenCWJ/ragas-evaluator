"""Suggestion generation, retrieval, update, apply, and batch-apply routes."""

import json

from fastapi import APIRouter, HTTPException

from app.routes.experiments import _sanitize_nan

from app.models import (
    ApplySuggestionRequest,
    BatchApplyRequest,
    SuggestionUpdate,
)
from app.routes.experiments import _parse_experiment_row
from evaluation.suggestions import apply_config_change, generate_suggestions
import db.init

router = APIRouter(prefix="/api", tags=["analyze"])


# ---------------------------------------------------------------------------
# 1. POST  Generate suggestions for a completed experiment
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/suggestions/generate"
)
async def generate_suggestions_route(project_id: int, experiment_id: int):
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
            detail="Experiment must be completed to generate suggestions",
        )

    # Fetch results
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()

    if not result_rows:
        raise HTTPException(status_code=409, detail="No results to analyze")

    # Compute aggregate metrics
    metric_totals: dict[str, float] = {}
    metric_counts: dict[str, int] = {}
    per_question_results: list[dict] = []
    for rr in result_rows:
        metrics = _sanitize_nan(json.loads(rr["metrics_json"])) if rr["metrics_json"] else {}
        per_question_results.append({"metrics": metrics})
        for metric_name, value in metrics.items():
            if value is not None:
                metric_totals[metric_name] = (
                    metric_totals.get(metric_name, 0.0) + value
                )
                metric_counts[metric_name] = (
                    metric_counts.get(metric_name, 0) + 1
                )

    aggregate: dict[str, float | None] = {}
    for mn in metric_totals:
        cnt = metric_counts[mn]
        aggregate[mn] = round(metric_totals[mn] / cnt, 4) if cnt > 0 else None

    # Generate suggestions via the rule-based engine
    new_suggestions = generate_suggestions(aggregate, per_question_results)

    # Atomic: delete old + insert new
    conn.execute(
        "DELETE FROM suggestions WHERE experiment_id = ?", (experiment_id,)
    )
    for s in new_suggestions:
        conn.execute(
            "INSERT INTO suggestions "
            "(experiment_id, category, signal, suggestion, priority, config_field, suggested_value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                experiment_id,
                s["category"],
                s["signal"],
                s["suggestion"],
                s["priority"],
                s.get("config_field"),
                s.get("suggested_value"),
            ),
        )
    conn.commit()

    # Re-read from DB to return actual state
    rows = conn.execute(
        "SELECT * FROM suggestions WHERE experiment_id = ? "
        "ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, category",
        (experiment_id,),
    ).fetchall()
    result = [dict(r) for r in rows]

    return {"suggestions": result, "count": len(result)}


# ---------------------------------------------------------------------------
# 2. GET  Retrieve suggestions for an experiment
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}/suggestions"
)
async def get_suggestions(project_id: int, experiment_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT id FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    rows = conn.execute(
        "SELECT * FROM suggestions WHERE experiment_id = ? "
        "ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, category",
        (experiment_id,),
    ).fetchall()

    return {"suggestions": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# 3. PATCH  Update suggestion implemented flag
# ---------------------------------------------------------------------------


@router.patch("/projects/{project_id}/suggestions/{suggestion_id}")
async def update_suggestion(
    project_id: int, suggestion_id: int, req: SuggestionUpdate
):
    conn = db.init.get_db()

    # Single JOIN query for cross-project isolation
    row = conn.execute(
        """SELECT s.* FROM suggestions s
           JOIN experiments e ON s.experiment_id = e.id
           WHERE s.id = ? AND e.project_id = ?""",
        (suggestion_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    conn.execute(
        "UPDATE suggestions SET implemented = ? WHERE id = ?",
        (req.implemented, suggestion_id),
    )
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()
    return dict(updated)


# ---------------------------------------------------------------------------
# 4. POST  Apply a single suggestion
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/suggestions/{suggestion_id}/apply")
async def apply_suggestion(
    project_id: int,
    suggestion_id: int,
    req: ApplySuggestionRequest | None = None,
):
    if req is None:
        req = ApplySuggestionRequest()

    conn = db.init.get_db()

    # Validate suggestion exists and belongs to project (JOIN through experiments)
    row = conn.execute(
        """SELECT s.*, e.id as exp_id, e.project_id as exp_project_id,
                  e.rag_config_id as exp_rag_config_id,
                  e.test_set_id, e.model, e.model_params_json, e.retrieval_config_json,
                  e.chunk_config_id as exp_chunk_config_id,
                  e.embedding_config_id as exp_embedding_config_id,
                  e.name as exp_name
           FROM suggestions s
           JOIN experiments e ON s.experiment_id = e.id
           WHERE s.id = ? AND e.project_id = ?""",
        (suggestion_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if row["implemented"]:
        raise HTTPException(status_code=409, detail="Suggestion already applied")

    if row["exp_rag_config_id"] is None:
        raise HTTPException(
            status_code=409, detail="Original experiment has no RAG config"
        )

    rag_config = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (row["exp_rag_config_id"], project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(
            status_code=409, detail="Original RAG config no longer exists"
        )

    config_field = row["config_field"]
    suggested_value = row["suggested_value"]

    if config_field is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This suggestion has no direct config mapping. "
                "It requires manual review — no automatic config change can be applied."
            ),
        )

    try:
        updated_fields, changes = apply_config_change(
            dict(rag_config), config_field, suggested_value, req.override_value
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Count existing iterations for naming
    iteration_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM experiments WHERE baseline_experiment_id = ?",
        (row["exp_id"],),
    ).fetchone()["cnt"]

    new_config_name = f"{rag_config['name']} \u2014 iteration {iteration_count + 1}"
    new_experiment_name = (
        req.experiment_name
        or f"{row['exp_name']} \u2014 iteration {iteration_count + 1}"
    )

    # Atomic transaction: INSERT config + INSERT experiment + UPDATE suggestion
    try:
        new_config_values = {
            "project_id": project_id,
            "name": new_config_name,
            "embedding_config_id": rag_config["embedding_config_id"],
            "chunk_config_id": rag_config["chunk_config_id"],
            "search_type": rag_config["search_type"],
            "sparse_config_id": rag_config["sparse_config_id"],
            "alpha": rag_config["alpha"],
            "llm_model": rag_config["llm_model"],
            "llm_params_json": rag_config["llm_params_json"],
            "top_k": rag_config["top_k"],
            "system_prompt": rag_config["system_prompt"],
            "response_mode": rag_config["response_mode"],
            "max_steps": rag_config["max_steps"],
        }
        for field, value in updated_fields.items():
            if field == "llm_params":
                new_config_values["llm_params_json"] = (
                    json.dumps(value) if value else None
                )
            else:
                new_config_values[field] = value

        cursor = conn.execute(
            """INSERT INTO rag_configs
               (project_id, name, embedding_config_id, chunk_config_id, search_type,
                sparse_config_id, alpha, llm_model, llm_params_json, top_k, system_prompt,
                response_mode, max_steps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_config_values["project_id"],
                new_config_values["name"],
                new_config_values["embedding_config_id"],
                new_config_values["chunk_config_id"],
                new_config_values["search_type"],
                new_config_values["sparse_config_id"],
                new_config_values["alpha"],
                new_config_values["llm_model"],
                new_config_values["llm_params_json"],
                new_config_values["top_k"],
                new_config_values["system_prompt"],
                new_config_values["response_mode"],
                new_config_values["max_steps"],
            ),
        )
        new_config_id = cursor.lastrowid

        # Snapshot retrieval config from new config values
        retrieval_config = json.dumps({
            "search_type": new_config_values["search_type"],
            "sparse_config_id": new_config_values["sparse_config_id"],
            "alpha": new_config_values["alpha"],
            "top_k": new_config_values["top_k"],
            "system_prompt": new_config_values["system_prompt"],
            "response_mode": new_config_values["response_mode"],
            "max_steps": new_config_values["max_steps"],
        })

        cursor2 = conn.execute(
            """INSERT INTO experiments
               (project_id, test_set_id, name, model, model_params_json, retrieval_config_json,
                chunk_config_id, embedding_config_id, rag_config_id, baseline_experiment_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                project_id,
                row["test_set_id"],
                new_experiment_name,
                row["model"],
                row["model_params_json"],
                retrieval_config,
                new_config_values["chunk_config_id"],
                new_config_values["embedding_config_id"],
                new_config_id,
                row["exp_id"],
            ),
        )
        new_experiment_id = cursor2.lastrowid

        conn.execute(
            "UPDATE suggestions SET implemented = TRUE WHERE id = ?",
            (suggestion_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    updated_suggestion = conn.execute(
        "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()
    new_experiment_row = conn.execute(
        "SELECT * FROM experiments WHERE id = ?", (new_experiment_id,)
    ).fetchone()

    return {
        "suggestion": dict(updated_suggestion),
        "new_experiment": _parse_experiment_row(new_experiment_row),
        "new_rag_config": {"id": new_config_id, "name": new_config_name},
        "changes": changes,
    }


# ---------------------------------------------------------------------------
# 5. POST  Batch-apply multiple suggestions
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/suggestions/apply-batch"
)
async def apply_suggestions_batch(
    project_id: int, experiment_id: int, req: BatchApplyRequest
):
    """Apply multiple suggestions at once, creating a single new RAG config and experiment."""
    if not req.items:
        raise HTTPException(status_code=400, detail="No suggestions provided")

    conn = db.init.get_db()

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["rag_config_id"] is None:
        raise HTTPException(
            status_code=409, detail="Experiment has no RAG config"
        )

    rag_config = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (experiment["rag_config_id"], project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(
            status_code=409, detail="Original RAG config no longer exists"
        )

    # Load and validate all suggestions
    suggestion_ids = [item.suggestion_id for item in req.items]
    override_map = {item.suggestion_id: item.override_value for item in req.items}

    placeholders = ",".join("?" * len(suggestion_ids))
    suggestions = conn.execute(
        f"""SELECT s.* FROM suggestions s
            WHERE s.id IN ({placeholders}) AND s.experiment_id = ?""",
        (*suggestion_ids, experiment_id),
    ).fetchall()

    if len(suggestions) != len(suggestion_ids):
        found_ids = {s["id"] for s in suggestions}
        missing = [sid for sid in suggestion_ids if sid not in found_ids]
        raise HTTPException(
            status_code=404, detail=f"Suggestions not found: {missing}"
        )

    errors: list[str] = []
    for s in suggestions:
        if s["implemented"]:
            errors.append(f"Suggestion {s['id']} already applied")
        if s["config_field"] is None:
            errors.append(
                f"Suggestion {s['id']} has no config mapping (manual review only)"
            )
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(errors))

    # Apply all changes sequentially to a running config dict
    config_dict = dict(rag_config)
    all_changes: dict = {}
    for s in suggestions:
        try:
            updated_fields, changes = apply_config_change(
                config_dict,
                s["config_field"],
                s["suggested_value"],
                override_map.get(s["id"]),
            )
            config_dict.update(updated_fields)
            all_changes.update(changes)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Suggestion {s['id']} ({s['config_field']}): {e}",
            )

    # Count existing iterations for naming
    iteration_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM experiments WHERE baseline_experiment_id = ?",
        (experiment_id,),
    ).fetchone()["cnt"]

    new_config_name = f"{rag_config['name']} \u2014 iteration {iteration_count + 1}"
    new_experiment_name = (
        req.experiment_name
        or f"{experiment['name']} \u2014 iteration {iteration_count + 1}"
    )

    try:
        new_config_values = {
            "project_id": project_id,
            "name": new_config_name,
            "embedding_config_id": config_dict["embedding_config_id"],
            "chunk_config_id": config_dict["chunk_config_id"],
            "search_type": config_dict["search_type"],
            "sparse_config_id": config_dict["sparse_config_id"],
            "alpha": config_dict["alpha"],
            "llm_model": config_dict["llm_model"],
            "llm_params_json": config_dict["llm_params_json"],
            "top_k": config_dict["top_k"],
            "system_prompt": config_dict["system_prompt"],
            "response_mode": config_dict["response_mode"],
            "max_steps": config_dict["max_steps"],
        }

        cursor = conn.execute(
            """INSERT INTO rag_configs
               (project_id, name, embedding_config_id, chunk_config_id, search_type,
                sparse_config_id, alpha, llm_model, llm_params_json, top_k, system_prompt,
                response_mode, max_steps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_config_values["project_id"],
                new_config_values["name"],
                new_config_values["embedding_config_id"],
                new_config_values["chunk_config_id"],
                new_config_values["search_type"],
                new_config_values["sparse_config_id"],
                new_config_values["alpha"],
                new_config_values["llm_model"],
                new_config_values["llm_params_json"],
                new_config_values["top_k"],
                new_config_values["system_prompt"],
                new_config_values["response_mode"],
                new_config_values["max_steps"],
            ),
        )
        new_config_id = cursor.lastrowid

        # Snapshot retrieval config from new config values
        retrieval_config = json.dumps({
            "search_type": new_config_values["search_type"],
            "sparse_config_id": new_config_values["sparse_config_id"],
            "alpha": new_config_values["alpha"],
            "top_k": new_config_values["top_k"],
            "system_prompt": new_config_values["system_prompt"],
            "response_mode": new_config_values["response_mode"],
            "max_steps": new_config_values["max_steps"],
        })

        cursor2 = conn.execute(
            """INSERT INTO experiments
               (project_id, test_set_id, name, model, model_params_json, retrieval_config_json,
                chunk_config_id, embedding_config_id, rag_config_id, baseline_experiment_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                project_id,
                experiment["test_set_id"],
                new_experiment_name,
                experiment["model"],
                experiment["model_params_json"],
                retrieval_config,
                new_config_values["chunk_config_id"],
                new_config_values["embedding_config_id"],
                new_config_id,
                experiment_id,
            ),
        )
        new_experiment_id = cursor2.lastrowid

        # Mark all suggestions as implemented
        conn.execute(
            f"UPDATE suggestions SET implemented = TRUE WHERE id IN ({placeholders})",
            suggestion_ids,
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Build response
    updated_suggestions = conn.execute(
        f"SELECT * FROM suggestions WHERE id IN ({placeholders})",
        suggestion_ids,
    ).fetchall()
    new_experiment_row = conn.execute(
        "SELECT * FROM experiments WHERE id = ?", (new_experiment_id,)
    ).fetchone()

    return {
        "suggestions": [dict(s) for s in updated_suggestions],
        "new_experiment": _parse_experiment_row(new_experiment_row),
        "new_rag_config": {"id": new_config_id, "name": new_config_name},
        "changes": all_changes,
    }
