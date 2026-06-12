"""Background experiment runner and aggregation helpers.

Extracted from app/routes/experiments.py so the route module stays a thin
HTTP layer. This module owns the run loop (question fan-out, judge blocks,
progress bookkeeping, cancellation, status transitions) plus the shared
row-aggregation/serialisation helpers used by several route modules.
"""

import asyncio
import json
import logging
import math
from dataclasses import asdict
from datetime import datetime

from fastapi import HTTPException

import db.init
from app.models import ExperimentRunRequest
from app.services.progress import experiment_runs
from config import BOT_QUERY_TIMEOUT
from evaluation.metrics import multi_llm_judge as _multi_llm_judge_module
from evaluation.metrics.custom_metric import CustomMetricConfig
from evaluation.scoring import ALL_METRICS, evaluate_experiment_row, setup_scorers
from pipeline.bot_connectors.factory import create_connector
from pipeline.rag import multi_step_query, single_shot_query

logger = logging.getLogger(__name__)

def parse_experiment_row(row) -> dict:
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


def build_virtual_rag_config_row(experiment_row, project_id: int) -> dict:
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
        "query_expansion": retrieval_config.get("query_expansion"),
        "num_expansions": retrieval_config.get("num_expansions"),
        "score_threshold": retrieval_config.get("score_threshold"),
        "mmr_lambda": retrieval_config.get("mmr_lambda"),
        "kg_expansion": retrieval_config.get("kg_expansion", 0),
    }



def sanitize_nan(obj):
    """Replace NaN/Inf floats with None so JSON serialization produces valid output."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_nan(v) for v in obj]
    return obj


def compute_aggregates(conn, exp_id: int) -> dict:
    """Compute per-metric averages for a completed experiment."""
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (exp_id,),
    ).fetchall()
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rr in result_rows:
        metrics = sanitize_nan(json.loads(rr["metrics_json"])) if rr["metrics_json"] else {}
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


def retrieval_diagnostics(
    q_metadata: dict | None, retrieved_contexts: list[dict]
) -> dict[str, float] | None:
    """Deterministic retrieval scores against question provenance.

    retrieval_hit_rate — 1.0 when ANY gold source chunk was retrieved
    retrieval_mrr      — 1/rank of the first gold chunk (0.0 when missed)

    Returns None when the question carries no provenance (uploaded legacy
    sets) or nothing was retrieved with chunk ids.
    """
    source_ids = set((q_metadata or {}).get("source_chunk_ids") or [])
    if not source_ids:
        return None
    retrieved_ids = [
        c.get("chunk_id") for c in retrieved_contexts if c.get("chunk_id") is not None
    ]
    if not retrieved_ids:
        return {"retrieval_hit_rate": 0.0, "retrieval_mrr": 0.0}
    for rank, cid in enumerate(retrieved_ids, 1):
        if cid in source_ids:
            return {"retrieval_hit_rate": 1.0, "retrieval_mrr": round(1.0 / rank, 4)}
    return {"retrieval_hit_rate": 0.0, "retrieval_mrr": 0.0}


def compute_token_usage(conn, exp_id: int) -> dict | None:
    """Sum prompt/completion tokens recorded in result metadata.

    Only generation-path tokens are recorded today (RAG queries through
    pipeline/llm.py); judge/metric scoring goes through ragas's own clients.
    Returns None when no usage was recorded at all.
    """
    rows = conn.execute(
        "SELECT metadata_json FROM experiment_results WHERE experiment_id = ?",
        (exp_id,),
    ).fetchall()
    prompt = completion = 0
    seen = False
    for r in rows:
        if not r["metadata_json"]:
            continue
        try:
            meta = json.loads(r["metadata_json"])
        except (TypeError, ValueError):
            continue
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else meta
        p = usage.get("prompt_tokens")
        c = usage.get("completion_tokens")
        if isinstance(p, int | float) or isinstance(c, int | float):
            seen = True
            prompt += int(p or 0)
            completion += int(c or 0)
    if not seen:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def aggregate_rows(result_rows) -> tuple[dict | None, float | None, int]:
    """Aggregate metric scores from experiment_results rows.

    Returns (aggregate_metrics, overall_score, result_count).
    Metrics with all-null values are omitted (unlike compute_aggregates).
    """
    n = len(result_rows)
    if not result_rows:
        return None, None, 0
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rr in result_rows:
        metrics = sanitize_nan(json.loads(rr["metrics_json"])) if rr["metrics_json"] else {}
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


async def run_experiment_background(
    *,
    experiment_id: int,
    project_id: int,
    experiment,
    selected_metrics: list[str],
    all_custom_rows,
    req: ExperimentRunRequest,
    cancel_event: asyncio.Event,
) -> None:
    """Run one experiment to completion in the background.

    Owns the full lifecycle after the route has claimed the experiment:
    scorer setup, concurrent question processing, judge passes, progress
    updates, cancellation, and the final status transition. Never raises —
    all failures are recorded in the progress store and the DB.
    """
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
        experiment_runs.set_progress(experiment_id, {
            "phase": "setup", "current": 0, "total": total,
            "question": "", "error": None, "result_count": 0,
            "completed_items": [],
            "in_flight": [],
            "in_flight_details": {},
            "setup_step": "Loading metric scorers...",
        })

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
                refined = cr.get("refined_prompt", None)
                few_shot = json.loads(cr["few_shot_examples_json"]) if "few_shot_examples_json" in cr and cr["few_shot_examples_json"] else None
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
                refined = cr.get("refined_prompt", None)
                few_shot = json.loads(cr["few_shot_examples_json"]) if "few_shot_examples_json" in cr and cr["few_shot_examples_json"] else None
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
        criteria_names | reference_names
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
        experiment_runs.set_progress(experiment_id, {
            "phase": "running", "current": 0, "total": total,
            "question": "", "error": None, "result_count": 0,
            "completed_items": [],
            "in_flight": [],
            "in_flight_details": {},
        })

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
                experiment_runs.set_progress(experiment_id, {
                    "phase": "error", "current": 0, "total": total,
                    "question": "", "error": "Bot config not found", "result_count": 0,
                })
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
            virtual_config = build_virtual_rag_config_row(experiment, project_id)

        # --- Concurrent question processing ---
        semaphore = asyncio.Semaphore(req.concurrency)
        progress_queue: asyncio.Queue = asyncio.Queue()

        async def _process_question(idx: int, q_row):
            """Process a single question under the semaphore.

            Questions whose metadata carries ``turns`` (a list of prior
            user messages) run as a CONVERSATION: each setup turn is sent
            with accumulated history, then the final question is asked and
            its answer evaluated. The transcript is stored with the result.
            """
            question_text = q_row["question"]
            qid = q_row["id"]
            conversation_turns = []
            try:
                _q_meta_early = json.loads(q_row["metadata_json"]) if q_row["metadata_json"] else {}
                raw_turns = _q_meta_early.get("turns") or []
                conversation_turns = [str(t) for t in raw_turns if str(t).strip()]
            except (TypeError, ValueError):
                conversation_turns = []

            async with semaphore:
                if cancel_event.is_set():
                    return  # skip if cancelled

                # Track in-flight question with detail
                all_metric_names = list(scorers.keys()) + list((custom_scorers or {}).keys())

                def _track_in_flight(prog: dict) -> None:
                    prog["in_flight"] = [*prog["in_flight"], question_text[:120]]
                    prog["in_flight_details"][qid] = {
                        "question": question_text[:200],
                        "phase": "scoring" if is_csv else "querying",
                        "metrics_done": [],
                        "metrics_active": [],
                        "metrics_pending": all_metric_names[:],
                    }

                experiment_runs.mutate_progress(experiment_id, _track_in_flight)

                try:
                    if is_csv:
                        # Look up the bot's actual answer from external_baselines;
                        # reference_answer (ground truth) comes from test_questions.
                        logger.info("CSV experiment %d: processing q%d '%s'", experiment_id, qid, question_text[:60])
                        csv_match = csv_answer_lookup.get(question_text.strip().lower())
                        if csv_match:
                            generated_answer = csv_match["answer"]
                            csv_match["sources"]
                        else:
                            generated_answer = (
                                q_row["user_edited_answer"]
                                if q_row["user_edited_answer"]
                                else q_row["reference_answer"]
                            ) or ""
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
                        # Multi-turn: play the setup turns first, carrying history
                        chat_history: list[dict] = []
                        for turn_text in conversation_turns:
                            prior = await asyncio.wait_for(
                                connector.query(turn_text, history=chat_history or None),
                                timeout=BOT_QUERY_TIMEOUT,
                            )
                            chat_history.append({"role": "user", "content": turn_text})
                            chat_history.append({"role": "assistant", "content": prior.answer})

                        bot_response = await asyncio.wait_for(
                            connector.query(question_text, history=chat_history or None),
                            timeout=BOT_QUERY_TIMEOUT,
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
                        if conversation_turns:
                            usage_info["transcript"] = chat_history
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
                    def _mark_scoring(prog: dict) -> None:
                        if qid in prog["in_flight_details"]:
                            prog["in_flight_details"][qid]["phase"] = "scoring"

                    experiment_runs.mutate_progress(experiment_id, _mark_scoring)

                    ref_answer = (
                        q_row["user_edited_answer"]
                        if q_row["user_edited_answer"]
                        else q_row["reference_answer"]
                    )
                    q_metadata = json.loads(q_row["metadata_json"]) if q_row["metadata_json"] else None
                    # Make the runtime transcript available to conversation
                    # metrics (conversation_retention). Internal RAG runs
                    # don't simulate turns — only bot runs build history.
                    if conversation_turns and use_bot and not is_csv:
                        q_metadata = {**(q_metadata or {}), "_transcript": chat_history}

                    def _on_metric_start(metric_name):
                        def _apply(prog: dict) -> None:
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

                        experiment_runs.mutate_progress(experiment_id, _apply)

                    def _on_metric_done(metric_name):
                        def _apply(prog: dict) -> None:
                            active = set(prog.get("scoring_metrics", []))
                            active.discard(metric_name)
                            prog["scoring_metrics"] = sorted(active)
                            # Per-question tracking
                            detail = prog.get("in_flight_details", {}).get(qid)
                            if detail is not None:
                                detail["metrics_active"] = [m for m in detail["metrics_active"] if m != metric_name]
                                if metric_name not in detail["metrics_done"]:
                                    detail["metrics_done"] = [*detail["metrics_done"], metric_name]

                        experiment_runs.mutate_progress(experiment_id, _apply)

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

                    # Deterministic retrieval diagnostics (internal RAG only):
                    # did retrieval fetch the chunk the gold answer lives in?
                    # Free and exact — splits "retrieval missed it" from
                    # "the model botched it". Needs question provenance
                    # (source_chunk_ids), recorded at generation time.
                    if not use_bot:
                        retrieval_metrics = retrieval_diagnostics(
                            q_metadata, full_context_dicts
                        )
                        if retrieval_metrics:
                            metrics_result.update(retrieval_metrics)

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
            except TimeoutError:
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
                        json.dumps(sanitize_nan(result["metrics_result"])),
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
                                (json.dumps(sanitize_nan(result["metrics_result"])), result_row_id),
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
                                (json.dumps(sanitize_nan(result["metrics_result"])), result_row_id),
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
                                (json.dumps(sanitize_nan(result["metrics_result"])), result_row_id),
                            )
                    except Exception as _rj_err:
                        logger.warning(
                            "Experiment %d: reference_judge '%s' failed for result %d: %s",
                            experiment_id, rj_config.metric_name, result_row_id, _rj_err,
                            exc_info=True,
                        )
                # --- End Reference Judges block ---
            else:
                run_conn = db.init.reconnect_if_needed(run_conn)
                run_conn.execute(
                    """INSERT INTO experiment_results
                       (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (experiment_id, qid, None, "[]", "{}", json.dumps(result["usage_info"])),
                )
            run_conn.commit()
            completed_count += 1

            # Update shared progress state (preserve accumulated lists).
            # Loop variables are bound as defaults so the closure captures
            # this iteration's values (B023).
            def _apply_result_progress(
                prog: dict,
                *,
                question_text=question_text,
                result=result,
                qid=qid,
                finished=finished,
                completed_count=completed_count,
            ) -> None:
                # Add to completed log (keep last 50 to bound memory)
                completed_items = [*prog.get("completed_items", [])[-49:], {
                    "question": question_text[:200],
                    "response": (result["generated_answer"] or "")[:300] if result["generated_answer"] else None,
                    "error": result["error"],
                    "metrics": result["metrics_result"] if result["error"] is None else {},
                }]

                # Remove from in-flight
                q_short = question_text[:120]
                in_flight = [q for q in prog.get("in_flight", []) if q != q_short]

                # Remove from in_flight_details
                in_flight_details = dict(prog.get("in_flight_details", {}))
                in_flight_details.pop(qid, None)

                prog.update({
                    "phase": "running", "current": finished, "total": total,
                    "question": question_text[:100],
                    "error": result["error"],
                    "result_count": completed_count,
                    "completed_items": completed_items,
                    "in_flight": in_flight,
                    "in_flight_details": in_flight_details,
                    "scoring_metrics": prog.get("scoring_metrics", []),
                })

            experiment_runs.mutate_progress(experiment_id, _apply_result_progress)

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
            experiment_runs.set_progress(experiment_id, {
                "phase": "cancelled", "current": finished, "total": total,
                "question": "", "error": None, "result_count": completed_count,
            })
        else:
            # All questions processed -- mark completed
            run_conn.execute(
                "UPDATE experiments SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), experiment_id),
            )
            run_conn.commit()
            experiment_runs.set_progress(experiment_id, {
                "phase": "completed", "current": finished, "total": total,
                "question": "", "error": None, "result_count": completed_count,
            })

    except Exception as e:
        import traceback
        logger.error("Experiment %d fatal error: %s\n%s", experiment_id, e, traceback.format_exc())
        experiment_runs.set_progress(experiment_id, {
            "phase": "error", "current": 0, "total": 0,
            "question": "", "error": str(e), "result_count": 0,
        })

    finally:
        experiment_runs.pop_cancel_event(experiment_id)
        experiment_runs.pop_task(experiment_id)
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
