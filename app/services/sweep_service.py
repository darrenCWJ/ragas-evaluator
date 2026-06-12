"""Parameter sweep service: expand a retrieval-parameter grid into experiments,
run them sequentially, and rank the results.

A sweep takes a base RAG config plus a grid of sweepable field values
(top_k, alpha, score_threshold, mmr_lambda, query expansion, reranker,
kg_expansion, llm_model), creates one experiment per combination — the same
snapshot shape as normal experiment creation, so the runner needs nothing
new — and awaits each through run_experiment_background. Default metrics are
judge-free (deterministic + embedding-only); retrieval_hit_rate / retrieval_mrr
arrive automatically through question provenance, so the leaderboard can rank
combinations without spending judge tokens. Judge the top finalists manually
afterwards.

Sweeps run inside the API process (one combination at a time). If the server
restarts mid-sweep, the sweep stays 'running' until cancelled via the cancel
endpoint — same recovery story as delegated experiments.
"""

import asyncio
import itertools
import json
import logging
from datetime import datetime

import db.init
from app.models import ExperimentRunRequest
from app.services.experiment_runner import aggregate_rows, run_experiment_background
from app.services.progress import experiment_runs

logger = logging.getLogger(__name__)

# Judge-free defaults: deterministic string metrics + embedding similarity.
DEFAULT_SWEEP_METRICS = [
    "bleu_score",
    "rouge_score",
    "non_llm_string_similarity",
    "semantic_similarity",
]

# Snapshot keys copied from the (override-patched) base config — keep in sync
# with create_experiment's snapshot in app/routes/experiments.py.
_SNAPSHOT_KEYS = [
    "search_type",
    "sparse_config_id",
    "alpha",
    "top_k",
    "system_prompt",
    "response_mode",
    "max_steps",
    "reranker_model",
    "reranker_top_k",
    "query_expansion",
    "num_expansions",
    "score_threshold",
    "mmr_lambda",
    "kg_expansion",
]


def expand_grid(grid: dict[str, list]) -> list[dict]:
    """Cartesian product of grid values, in deterministic key order."""
    keys = sorted(grid.keys())
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*(grid[k] for k in keys))]


def params_label(params: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(params.items()))


def create_sweep_experiment(conn, sweep_row, base_config, params: dict) -> int:
    """Insert one pending experiment for a parameter combination."""
    cfg = {**dict(base_config), **params}
    retrieval_config = json.dumps({key: cfg.get(key) for key in _SNAPSHOT_KEYS})
    cursor = conn.execute(
        """INSERT INTO experiments
           (project_id, test_set_id, name, model, model_params_json, retrieval_config_json,
            chunk_config_id, embedding_config_id, rag_config_id, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending')""",
        (
            sweep_row["project_id"],
            sweep_row["test_set_id"],
            f"{sweep_row['name']} · {params_label(params)}"[:200],
            cfg["llm_model"],
            base_config["llm_params_json"],
            retrieval_config,
            base_config["chunk_config_id"],
            base_config["embedding_config_id"],
        ),
    )
    conn.commit()
    return cursor.lastrowid


def _set_sweep_status(conn, sweep_id: int, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE sweeps SET status = ?, error_message = ? WHERE id = ?",
        (status, error, sweep_id),
    )
    conn.commit()


def _sweep_cancelled(conn, sweep_id: int) -> bool:
    row = conn.execute("SELECT status FROM sweeps WHERE id = ?", (sweep_id,)).fetchone()
    return row is None or row["status"] == "cancelled"


async def run_sweep_background(sweep_id: int) -> None:
    """Run every pending combination of a sweep, one at a time. Never raises."""
    conn = db.init.get_thread_db()
    try:
        sweep = conn.execute("SELECT * FROM sweeps WHERE id = ?", (sweep_id,)).fetchone()
        if sweep is None:
            return
        base_config = conn.execute(
            "SELECT * FROM rag_configs WHERE id = ?", (sweep["base_rag_config_id"],)
        ).fetchone()
        if base_config is None:
            _set_sweep_status(conn, sweep_id, "failed", "Base RAG config was deleted")
            return

        metrics = json.loads(sweep["metrics_json"])
        _set_sweep_status(conn, sweep_id, "running")

        runs = conn.execute(
            "SELECT * FROM sweep_runs WHERE sweep_id = ? AND status = 'pending' ORDER BY id",
            (sweep_id,),
        ).fetchall()

        for run in runs:
            if _sweep_cancelled(conn, sweep_id):
                logger.info("Sweep %d cancelled — stopping before run %d", sweep_id, run["id"])
                return

            params = json.loads(run["params_json"])
            experiment_id = create_sweep_experiment(conn, sweep, base_config, params)
            conn.execute(
                "UPDATE sweep_runs SET experiment_id = ?, status = 'running' WHERE id = ?",
                (experiment_id, run["id"]),
            )
            # Claim the experiment exactly like the run route does.
            conn.execute(
                "UPDATE experiments SET status = 'running', started_at = ? WHERE id = ?",
                (datetime.now().isoformat(), experiment_id),
            )
            conn.commit()

            experiment = conn.execute(
                "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
            cancel_event = asyncio.Event()
            experiment_runs.set_cancel_event(experiment_id, cancel_event)
            experiment_runs.set_progress(experiment_id, {
                "phase": "starting", "current": 0, "total": 0,
                "question": "", "error": None, "result_count": 0,
                "completed_items": [], "in_flight": [], "scoring_metrics": [],
            })

            logger.info(
                "Sweep %d: running experiment %d (%s)",
                sweep_id, experiment_id, params_label(params),
            )
            await run_experiment_background(
                experiment_id=experiment_id,
                project_id=sweep["project_id"],
                experiment=experiment,
                selected_metrics=metrics,
                all_custom_rows=[],
                req=ExperimentRunRequest(metrics=metrics),
                cancel_event=cancel_event,
            )

            final = conn.execute(
                "SELECT status FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
            run_status = "completed" if final and final["status"] == "completed" else "failed"
            conn.execute(
                "UPDATE sweep_runs SET status = ? WHERE id = ?", (run_status, run["id"])
            )
            conn.commit()

        if not _sweep_cancelled(conn, sweep_id):
            failed = conn.execute(
                "SELECT COUNT(*) AS cnt FROM sweep_runs WHERE sweep_id = ? AND status = 'failed'",
                (sweep_id,),
            ).fetchone()["cnt"]
            _set_sweep_status(conn, sweep_id, "completed" if failed == 0 else "completed_with_failures")
            logger.info("Sweep %d finished (%d failed runs)", sweep_id, failed)

    except Exception as exc:
        logger.exception("Sweep %d fatal error", sweep_id)
        try:
            _set_sweep_status(conn, sweep_id, "failed", str(exc)[:500])
        except Exception:
            logger.exception("Sweep %d: could not record failure status", sweep_id)
    finally:
        conn.close()


# Leaderboard ranking preference: provenance-based retrieval quality first,
# then the cross-metric overall score.
_RANK_METRIC = "retrieval_hit_rate"


def sweep_leaderboard(conn, sweep_id: int) -> list[dict]:
    """Per-combination aggregates, best first."""
    runs = conn.execute(
        "SELECT * FROM sweep_runs WHERE sweep_id = ? ORDER BY id", (sweep_id,)
    ).fetchall()
    entries = []
    for run in runs:
        aggregate, overall, count = None, None, 0
        if run["experiment_id"] is not None:
            rows = conn.execute(
                "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
                (run["experiment_id"],),
            ).fetchall()
            aggregate, overall, count = aggregate_rows(rows)
        entries.append({
            "run_id": run["id"],
            "experiment_id": run["experiment_id"],
            "params": json.loads(run["params_json"]),
            "status": run["status"],
            "aggregate_metrics": aggregate,
            "overall_score": overall,
            "result_count": count,
        })

    def sort_key(entry: dict):
        agg = entry["aggregate_metrics"] or {}
        rank = agg.get(_RANK_METRIC)
        overall = entry["overall_score"]
        return (
            rank is not None,
            rank if rank is not None else 0.0,
            overall is not None,
            overall if overall is not None else 0.0,
        )

    entries.sort(key=sort_key, reverse=True)
    return entries
