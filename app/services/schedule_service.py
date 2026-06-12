"""Scheduled regression runs against external agents, with drop alerts.

A schedule re-runs a bot-connector experiment on an interval (judge-free
metrics by default), compares each run's aggregate metrics to the previous
scheduled run, and raises an alert when any shared metric drops by more than
the configured threshold. Alerts are stored in schedule_alerts (surfaced via
the API) and optionally POSTed to a webhook, best-effort.

The ticker runs inside the API process (started from the app lifespan, same
pattern as the worker-experiment monitor). One due schedule runs at a time.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import db.init
from app.models import ExperimentRunRequest
from app.services.experiment_runner import compute_aggregates, run_experiment_background
from app.services.progress import experiment_runs
from logging_utils import clean

logger = logging.getLogger(__name__)

TICK_SECONDS = 60

DEFAULT_SCHEDULE_METRICS = [
    "bleu_score",
    "rouge_score",
    "non_llm_string_similarity",
    "semantic_similarity",
]


def find_due_schedules(conn, now: datetime) -> list:
    """Enabled schedules whose interval has elapsed since their last run."""
    rows = conn.execute("SELECT * FROM schedules WHERE enabled = 1").fetchall()
    due = []
    for row in rows:
        last = row["last_run_at"]
        if last is None:
            due.append(row)
            continue
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            due.append(row)
            continue
        if now - last_dt >= timedelta(minutes=row["interval_minutes"]):
            due.append(row)
    return due


def detect_drops(baseline: dict, current: dict, threshold: float) -> list[dict]:
    """Metrics present in both aggregates that fell by more than threshold."""
    drops = []
    for metric, base_value in baseline.items():
        cur_value = current.get(metric)
        if base_value is None or cur_value is None:
            continue
        drop = round(base_value - cur_value, 4)
        if drop > threshold:
            drops.append({
                "metric": metric,
                "baseline": base_value,
                "current": cur_value,
                "drop": drop,
            })
    return drops


async def _post_webhook(url: str, payload: dict) -> None:
    """Best-effort alert delivery — failures are logged, never raised."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        logger.warning("Schedule alert webhook %s failed: %s", url, exc)


async def run_scheduled_check(schedule_id: int) -> int | None:
    """Run one scheduled regression experiment; returns the experiment id."""
    conn = db.init.get_thread_db()
    try:
        schedule = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if schedule is None:
            return None
        bot_config = conn.execute(
            "SELECT * FROM bot_configs WHERE id = ?", (schedule["bot_config_id"],)
        ).fetchone()
        if bot_config is None:
            logger.warning("Schedule %d: bot config deleted — disabling", schedule_id)
            conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (schedule_id,))
            conn.commit()
            return None

        now_iso = datetime.now().isoformat()
        # Stamp last_run_at up front so a crash can't cause a tight retry loop.
        conn.execute(
            "UPDATE schedules SET last_run_at = ? WHERE id = ?", (now_iso, schedule_id)
        )

        cursor = conn.execute(
            """INSERT INTO experiments
               (project_id, test_set_id, name, model, bot_config_id, status, started_at)
               VALUES (?, ?, ?, ?, ?, 'running', ?)""",
            (
                schedule["project_id"],
                schedule["test_set_id"],
                f"[scheduled] {schedule['name']} @ {now_iso[:16]}"[:200],
                f"{bot_config['connector_type']}:{bot_config['name']}",
                schedule["bot_config_id"],
                now_iso,
            ),
        )
        experiment_id = cursor.lastrowid
        conn.commit()

        experiment = conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        metrics = json.loads(schedule["metrics_json"])
        cancel_event = asyncio.Event()
        experiment_runs.set_cancel_event(experiment_id, cancel_event)
        experiment_runs.set_progress(experiment_id, {
            "phase": "starting", "current": 0, "total": 0,
            "question": "", "error": None, "result_count": 0,
            "completed_items": [], "in_flight": [], "scoring_metrics": [],
        })

        logger.info("Schedule %d: running regression experiment %d", schedule_id, experiment_id)
        await run_experiment_background(
            experiment_id=experiment_id,
            project_id=schedule["project_id"],
            experiment=experiment,
            selected_metrics=metrics,
            all_custom_rows=[],
            req=ExperimentRunRequest(metrics=metrics),
            cancel_event=cancel_event,
        )

        final = conn.execute(
            "SELECT status FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        if final is None or final["status"] != "completed":
            logger.warning(
                "Schedule %d: regression run %d ended %s — skipping comparison",
                schedule_id, experiment_id, clean(final["status"]) if final else "missing",
            )
            return experiment_id

        baseline_experiment_id = schedule["last_experiment_id"]
        if baseline_experiment_id is not None:
            baseline = compute_aggregates(conn, baseline_experiment_id)
            current = compute_aggregates(conn, experiment_id)
            drops = detect_drops(baseline, current, schedule["alert_drop_threshold"])
            if drops:
                conn.execute(
                    """INSERT INTO schedule_alerts
                       (schedule_id, experiment_id, baseline_experiment_id, drops_json)
                       VALUES (?, ?, ?, ?)""",
                    (schedule_id, experiment_id, baseline_experiment_id, json.dumps(drops)),
                )
                conn.commit()
                logger.warning(
                    "Schedule %d ALERT: %d metric(s) dropped on experiment %d: %s",
                    schedule_id, len(drops), experiment_id,
                    clean(", ".join(f"{d['metric']} -{d['drop']}" for d in drops)),
                )
                if schedule["webhook_url"]:
                    await _post_webhook(schedule["webhook_url"], {
                        "schedule_id": schedule_id,
                        "schedule_name": schedule["name"],
                        "experiment_id": experiment_id,
                        "baseline_experiment_id": baseline_experiment_id,
                        "drops": drops,
                    })

        conn.execute(
            "UPDATE schedules SET last_experiment_id = ? WHERE id = ?",
            (experiment_id, schedule_id),
        )
        conn.commit()
        return experiment_id
    except Exception:
        logger.exception("Schedule %d: regression check failed", schedule_id)
        return None
    finally:
        conn.close()


async def schedule_loop() -> None:
    """Tick every TICK_SECONDS and run due schedules one at a time."""
    logger.info("Schedule loop started (tick %ds)", TICK_SECONDS)
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            conn = db.init.get_thread_db()
            try:
                due = find_due_schedules(conn, datetime.now())
            finally:
                conn.close()
            for schedule in due:
                await run_scheduled_check(schedule["id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Schedule loop tick failed")
