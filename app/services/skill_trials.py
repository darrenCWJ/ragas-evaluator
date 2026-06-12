"""Skill trial runner — execute a (skill | baseline) × model × question matrix.

Each cell: inject the skill as system context, query the target AI, judge the
response against the skill's directive checklist, and persist the result with
a step-level trace. Baseline cells (no skill) are judged against the same
checklist so per-model *lift* is measurable.

Model specs (trial ``models_json`` entries):
    {"kind": "llm", "model": "gpt-4o-mini"}           → pipeline.llm.chat_completion
    {"kind": "bot", "bot_config_id": 3, "label": ...} → bot connector with system_context
"""

import asyncio
import json
import logging
import time
from datetime import datetime

import db.init
from app.services.progress import ProgressStore
from app.services.tracing import TraceRecorder
from config import BOT_QUERY_TIMEOUT
from evaluation.skills.adherence import judge_adherence
from pipeline.bot_connectors.factory import create_connector
from pipeline.llm import chat_completion
from pipeline.retry import with_backoff

logger = logging.getLogger(__name__)

# Separate store from experiment runs — trial ids and experiment ids share
# the integer keyspace.
skill_trial_runs = ProgressStore()

_CELL_CONCURRENCY = 4


def model_spec_label(spec: dict) -> str:
    if spec.get("kind") == "bot":
        return spec.get("label") or f"bot:{spec.get('bot_config_id')}"
    return spec.get("model", "unknown")


async def _query_model(
    spec: dict,
    question: str,
    system_context: str | None,
    conn,
) -> dict:
    """Query one model spec. Returns {answer, tokens_in, tokens_out}."""
    if spec.get("kind") == "bot":
        bot_cfg = conn.execute(
            "SELECT * FROM bot_configs WHERE id = ?", (spec["bot_config_id"],)
        ).fetchone()
        if bot_cfg is None:
            raise ValueError(f"Bot config {spec['bot_config_id']} not found")
        config_dict = json.loads(bot_cfg["config_json"]) if bot_cfg["config_json"] else {}
        connector = create_connector(
            bot_cfg["connector_type"],
            config_dict,
            prompt_for_sources=False,
        )
        response = await asyncio.wait_for(
            connector.query(question, system_context=system_context),
            timeout=BOT_QUERY_TIMEOUT,
        )
        usage = response.raw_response.get("usage", {}) if response.raw_response else {}
        return {
            "answer": response.answer,
            "tokens_in": usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
            "tokens_out": usage.get("completion_tokens") or usage.get("output_tokens") or 0,
        }

    messages = []
    if system_context:
        messages.append({"role": "system", "content": system_context})
    messages.append({"role": "user", "content": question})

    async def _call():
        return await chat_completion(spec["model"], messages, {"max_tokens": 4096})

    result = await with_backoff(_call, attempts=3, label=f"skill-trial:{spec['model']}")
    usage = result.get("usage", {})
    return {
        "answer": result["content"],
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
    }


_MAX_USER_EXCHANGES = 3


async def _simulate_user_reply(
    original_question: str,
    assistant_question: str,
    brief: str | None = None,
) -> str:
    """LLM plays the user when a skill asks a clarifying question mid-flow.

    With a *brief* (full project/task details supplied by the human), the
    simulator answers each question FROM those details — so any model can ask
    anything, in any order, and still get the right answer.
    """
    from config import DEFAULT_EVAL_MODEL

    brief_block = (
        "Here is everything you know about your project/task — answer from "
        f"these details whenever they cover the question:\n{brief}\n\n"
        if brief else ""
    )
    prompt = (
        "You are simulating the USER in a conversation with an AI assistant. "
        f"Your original request was:\n{original_question}\n\n"
        + brief_block
        + f"The assistant asked you:\n{assistant_question}\n\n"
        "Reply briefly (1-2 sentences), staying consistent with your original "
        "request"
        + (" and the details above" if brief else "")
        + ". If the details don't cover the question, give a short sensible "
        "answer consistent with them. Output the user reply only."
    )
    response = await chat_completion(
        DEFAULT_EVAL_MODEL,
        [{"role": "user", "content": prompt}],
        {"temperature": 0.3, "max_tokens": 200},
    )
    return response["content"]


async def _query_model_agentic(
    spec: dict,
    q_row: dict,
    system_context: str | None,
    skill_files: dict[str, str],
    user_brief: str | None = None,
) -> dict:
    """Agentic cell: the model can read skill reference files on demand
    (progressive disclosure) and ask a simulated user clarifying questions.

    Scripted answers (question metadata ``user_inputs``) take priority over
    the LLM user simulator and are consumed in order.
    """
    from app.services.scripted_replies import ScriptedReplies
    from pipeline.agent_loop import run_agent

    question = q_row["question"]
    try:
        q_meta = json.loads(q_row["metadata_json"]) if q_row.get("metadata_json") else {}
    except (TypeError, ValueError):
        q_meta = {}
    scripted = ScriptedReplies(
        [str(s) for s in (q_meta.get("user_inputs") or []) if str(s).strip()]
    )
    exchanges = {"n": 0}

    tools: list[dict] = [{
        "name": "ask_user",
        "description": "Ask the user a clarifying question and receive their reply.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Question for the user"}},
            "required": ["question"],
        },
    }]
    if skill_files:
        tools.append({
            "name": "read_file",
            "description": (
                "Read one of the skill's reference files by path. Available: "
                + ", ".join(sorted(skill_files))
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"],
            },
        })

    async def executor(name: str, args: dict) -> str:
        if name == "read_file":
            path = str(args.get("path", "")).strip().lstrip("./")
            for file_path, content in skill_files.items():
                if file_path == path or file_path.endswith("/" + path):
                    return content
            return f"File '{path}' not found. Available: {', '.join(sorted(skill_files)) or '(none)'}"
        if name == "ask_user":
            exchanges["n"] += 1
            asked = str(args.get("question", ""))
            reply = scripted.take(asked)
            if reply is not None:
                return reply
            if exchanges["n"] > _MAX_USER_EXCHANGES:
                return "No further input — proceed with your best judgment."
            return await _simulate_user_reply(question, asked, brief=user_brief)
        return f"Error: unknown tool '{name}'"

    messages: list[dict] = []
    if system_context:
        messages.append({"role": "system", "content": system_context})
    messages.append({"role": "user", "content": question})

    # Process-flow skills walk many stages (read tier file → ask → act), so
    # give the loop more round-trips than the general default.
    result = await run_agent(
        spec["model"], messages, tools, executor, params={"max_tokens": 4096}, max_steps=16
    )
    files_read = [
        str(s["arguments"].get("path", "")) for s in result["steps"] if s["tool"] == "read_file"
    ]
    return {
        "answer": result["answer"],
        "tokens_in": result["usage"]["prompt_tokens"],
        "tokens_out": result["usage"]["completion_tokens"],
        "agent_steps": result["steps"],
        "agent_turns": result.get("turns", []),
        "files_read": files_read,
        "user_exchanges": exchanges["n"],
    }


def _stage_metrics(stages: list[dict], files_read: list[str]) -> dict | None:
    """Score how well an agentic run walked a staged skill's file plan.

    stage_coverage — fraction of stage-plan files the model actually read.
    stage_order    — fraction of consecutive stage-file reads in plan order.
    """
    plan_files: list[str] = []
    seen: set[str] = set()
    for stage in stages:
        for path in stage.get("files", []):
            if path not in seen:
                seen.add(path)
                plan_files.append(path)
    if not plan_files:
        return None

    def _first_read_index(path: str) -> int | None:
        for i, read in enumerate(files_read):
            if read == path or read.endswith("/" + path) or path.endswith("/" + read):
                return i
        return None

    read_indices = [idx for idx in (_first_read_index(p) for p in plan_files) if idx is not None]
    coverage = len(read_indices) / len(plan_files)
    if len(read_indices) >= 2:
        in_order = sum(
            1 for a, b in zip(read_indices, read_indices[1:], strict=False) if a <= b
        )
        order = in_order / (len(read_indices) - 1)
    else:
        order = 1.0 if read_indices else 0.0
    return {
        "stage_coverage": round(coverage, 4),
        "stage_order": round(order, 4),
        "stage_files_total": len(plan_files),
    }


async def _run_cell(
    trial_id: int,
    skill: dict | None,
    directives: list[dict],
    spec: dict,
    q_row: dict,
    judge_model: str | None,
    semaphore: asyncio.Semaphore,
    cancel_event: asyncio.Event,
    mode: str = "inline",
    skill_files: dict[str, str] | None = None,
    stages: list[dict] | None = None,
) -> dict | None:
    """Run one matrix cell. Returns a result-row dict or None when cancelled."""
    label = model_spec_label(spec)
    variant = "skill" if skill else "baseline"
    trace = TraceRecorder(
        f"skill-trial-{trial_id}",
        {"trial_id": trial_id, "model": label, "variant": variant, "question_id": q_row["id"]},
    )
    row: dict = {
        "trial_id": trial_id,
        "skill_id": skill["id"] if skill else None,
        "model": label,
        "test_question_id": q_row["id"],
        "response": None,
        "scores_json": None,
        "directive_results_json": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "error": None,
    }
    async with semaphore:
        if cancel_event.is_set():
            return None
        conn = db.init.get_db()
        try:
            with trace.span("prepare", skill_chars=len(skill["content"]) if skill else 0):
                system_context = skill["content"] if skill else None

            # Agentic mode applies to direct-LLM specs only — bot connectors
            # cannot run the tool loop and fall back to inline injection.
            agentic = mode == "agentic" and spec.get("kind") != "bot"

            t0 = time.monotonic()
            with trace.span("query", model=label, mode="agentic" if agentic else "inline"):
                if agentic:
                    reply = await _query_model_agentic(
                        spec, q_row, system_context, skill_files or {}
                    )
                else:
                    reply = await _query_model(spec, q_row["question"], system_context, conn)
            row["latency_ms"] = int((time.monotonic() - t0) * 1000)
            row["response"] = reply["answer"]
            row["tokens_in"] = int(reply["tokens_in"] or 0)
            row["tokens_out"] = int(reply["tokens_out"] or 0)
            # The model's visible process: per LLM round, the narrated thought
            # plus the tool calls it made — interleaved so the drilldown reads
            # like a transcript of how the model worked through the skill.
            turns = reply.get("agent_turns") or []
            if turns:
                for i, turn in enumerate(turns, 1):
                    if turn.get("thought"):
                        with trace.span(
                            f"thinking:{i}",
                            text=turn["thought"][:2000],
                            llm_ms=turn.get("latency_ms"),
                        ):
                            pass
                    for step in turn.get("steps", []):
                        with trace.span(
                            f"tool:{step['tool']}",
                            arguments=json.dumps(step["arguments"])[:500],
                            result=str(step["result"])[:500],
                            error=step.get("error"),
                        ):
                            pass
            else:
                for step in reply.get("agent_steps", []):
                    with trace.span(
                        f"tool:{step['tool']}",
                        arguments=json.dumps(step["arguments"])[:500],
                        result=str(step["result"])[:500],
                        error=step.get("error"),
                    ):
                        pass

            with trace.span("judge", directives=len(directives)):
                verdicts = await judge_adherence(
                    q_row["question"], reply["answer"], directives, judge_model=judge_model
                )
            results = verdicts["results"]
            fmt_checked = [r for r in results if r["deterministic"]]
            fmt_score = (
                sum(1 for r in fmt_checked if r["verdict"] == "pass") / len(fmt_checked)
                if fmt_checked else None
            )
            scores = {
                "skill_adherence": verdicts["score"],
                "format_compliance": fmt_score,
            }
            if agentic:
                scores["files_read_count"] = len(reply.get("files_read", []))
                scores["user_exchanges"] = reply.get("user_exchanges", 0)
                if skill and stages:
                    stage_scores = _stage_metrics(stages, reply.get("files_read", []))
                    if stage_scores:
                        scores.update(stage_scores)
            row["scores_json"] = json.dumps(scores)
            row["directive_results_json"] = json.dumps(results)
        except Exception as exc:
            logger.warning(
                "Skill trial %d cell failed (model=%s q=%d): %s",
                trial_id, label, q_row["id"], exc,
            )
            row["error"] = str(exc)[:1000]
        row["trace_json"] = json.dumps(trace.to_list())
        trace.export()
    return row


def _progress_init(trial_id: int, total: int) -> None:
    skill_trial_runs.set_progress(trial_id, {
        "phase": "running", "current": 0, "total": total, "error": None,
    })


async def run_skill_trial(trial_id: int) -> None:
    """Execute a trial end-to-end. Designed to run as an asyncio background task."""
    conn = db.init.get_thread_db()
    cancel_event = asyncio.Event()
    skill_trial_runs.set_cancel_event(trial_id, cancel_event)
    try:
        trial = conn.execute("SELECT * FROM skill_trials WHERE id = ?", (trial_id,)).fetchone()
        if trial is None:
            raise ValueError(f"Trial {trial_id} not found")

        skill = None
        directives: list[dict] = []
        stages: list[dict] = []
        if trial["skill_id"]:
            skill_row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (trial["skill_id"],)
            ).fetchone()
            if skill_row is None:
                raise ValueError(f"Skill {trial['skill_id']} not found")
            skill = dict(skill_row)
            parsed = json.loads(skill["parsed_directives_json"] or "{}")
            directives = parsed.get("directives", [])
            stages = parsed.get("stages")
            if stages is None:
                from evaluation.skills.parser import extract_stages
                stages = extract_stages(skill["content"] or "")
        if not directives:
            raise ValueError("Trial skill has no parsed directives — re-upload the skill")

        mode = trial["mode"] or "inline"
        skill_files: dict[str, str] = {}
        if mode == "agentic" and trial["skill_id"]:
            skill_files = {
                r["path"]: r["content"]
                for r in conn.execute(
                    "SELECT path, content FROM skill_files WHERE skill_id = ?",
                    (trial["skill_id"],),
                ).fetchall()
            }

        specs = json.loads(trial["models_json"])
        questions = conn.execute(
            "SELECT * FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited') ORDER BY id",
            (trial["test_set_id"],),
        ).fetchall()
        if not questions:
            raise ValueError("Test set has no approved questions")

        proj = conn.execute(
            "SELECT judge_model_assignments_json FROM projects WHERE id = ?",
            (trial["project_id"],),
        ).fetchone()
        judge_model = None
        if proj and proj["judge_model_assignments_json"]:
            assignments = json.loads(proj["judge_model_assignments_json"])
            judge_model = assignments[0] if assignments else None

        variants: list[dict | None] = [skill]
        if trial["include_baseline"]:
            variants.append(None)

        cells = [
            (variant, spec, dict(q))
            for variant in variants
            for spec in specs
            for q in questions
        ]
        _progress_init(trial_id, len(cells))
        conn.execute(
            "UPDATE skill_trials SET status = 'running' WHERE id = ?", (trial_id,)
        )
        conn.commit()

        semaphore = asyncio.Semaphore(_CELL_CONCURRENCY)
        tasks = [
            asyncio.create_task(_run_cell(
                trial_id, variant, directives, spec, q, judge_model, semaphore, cancel_event,
                mode=mode, skill_files=skill_files, stages=stages,
            ))
            for variant, spec, q in cells
        ]

        for done, fut in enumerate(asyncio.as_completed(tasks), 1):
            row = await fut
            if row is not None:
                conn = db.init.reconnect_if_needed(conn)
                conn.execute(
                    """INSERT INTO skill_trial_results
                       (trial_id, skill_id, model, test_question_id, response,
                        scores_json, directive_results_json, trace_json,
                        tokens_in, tokens_out, latency_ms, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["trial_id"], row["skill_id"], row["model"],
                        row["test_question_id"], row["response"],
                        row["scores_json"], row["directive_results_json"],
                        row["trace_json"], row["tokens_in"], row["tokens_out"],
                        row["latency_ms"], row["error"],
                    ),
                )
                conn.commit()
            skill_trial_runs.mutate_progress(trial_id, lambda p, _d=done: p.update(current=_d))
            if cancel_event.is_set():
                break

        if cancel_event.is_set():
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            status, phase = "cancelled", "cancelled"
        else:
            status, phase = "completed", "completed"
        conn.execute(
            "UPDATE skill_trials SET status = ?, completed_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(), trial_id),
        )
        conn.commit()
        skill_trial_runs.mutate_progress(trial_id, lambda p: p.update(phase=phase))
    except Exception as exc:
        logger.exception("Skill trial %d failed: %s", trial_id, exc)
        try:
            conn.execute(
                "UPDATE skill_trials SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                (str(exc)[:1000], datetime.now().isoformat(), trial_id),
            )
            conn.commit()
        except Exception:
            logger.warning("Could not persist trial %d failure state", trial_id, exc_info=True)
        skill_trial_runs.set_progress(trial_id, {
            "phase": "error", "current": 0, "total": 0, "error": str(exc)[:500],
        })
    finally:
        skill_trial_runs.pop_cancel_event(trial_id)
        skill_trial_runs.pop_task(trial_id)
        conn.close()


def aggregate_trial_matrix(conn, trial_id: int) -> dict:
    """Build the model × variant matrix with adherence/lift aggregates."""
    rows = conn.execute(
        """SELECT model, skill_id, scores_json, tokens_in, tokens_out, latency_ms, error
           FROM skill_trial_results WHERE trial_id = ?""",
        (trial_id,),
    ).fetchall()

    cells: dict[tuple[str, str], dict] = {}
    for r in rows:
        variant = "skill" if r["skill_id"] else "baseline"
        key = (r["model"], variant)
        cell = cells.setdefault(key, {
            "model": r["model"], "variant": variant,
            "adherence_sum": 0.0, "adherence_n": 0,
            "format_sum": 0.0, "format_n": 0,
            "stage_cov_sum": 0.0, "stage_order_sum": 0.0, "stage_n": 0,
            "tokens_in": 0, "tokens_out": 0,
            "latency_sum": 0, "latency_n": 0,
            "errors": 0, "count": 0,
        })
        cell["count"] += 1
        cell["tokens_in"] += r["tokens_in"] or 0
        cell["tokens_out"] += r["tokens_out"] or 0
        if r["latency_ms"]:
            cell["latency_sum"] += r["latency_ms"]
            cell["latency_n"] += 1
        if r["error"]:
            cell["errors"] += 1
            continue
        scores = json.loads(r["scores_json"]) if r["scores_json"] else {}
        if scores.get("skill_adherence") is not None:
            cell["adherence_sum"] += scores["skill_adherence"]
            cell["adherence_n"] += 1
        if scores.get("format_compliance") is not None:
            cell["format_sum"] += scores["format_compliance"]
            cell["format_n"] += 1
        if scores.get("stage_coverage") is not None:
            cell["stage_cov_sum"] += scores["stage_coverage"]
            cell["stage_order_sum"] += scores.get("stage_order") or 0.0
            cell["stage_n"] += 1

    out = []
    by_model: dict[str, dict] = {}
    for (model, variant), c in cells.items():
        adherence = round(c["adherence_sum"] / c["adherence_n"], 4) if c["adherence_n"] else None
        entry = {
            "model": model,
            "variant": variant,
            "adherence": adherence,
            "format_compliance": round(c["format_sum"] / c["format_n"], 4) if c["format_n"] else None,
            "stage_coverage": round(c["stage_cov_sum"] / c["stage_n"], 4) if c["stage_n"] else None,
            "stage_order": round(c["stage_order_sum"] / c["stage_n"], 4) if c["stage_n"] else None,
            "avg_latency_ms": int(c["latency_sum"] / c["latency_n"]) if c["latency_n"] else None,
            "tokens_in": c["tokens_in"],
            "tokens_out": c["tokens_out"],
            "errors": c["errors"],
            "count": c["count"],
        }
        out.append(entry)
        by_model.setdefault(model, {})[variant] = adherence

    # skill_lift = skill adherence − baseline adherence, per model
    lifts = {}
    for model, variants in by_model.items():
        if variants.get("skill") is not None and variants.get("baseline") is not None:
            lifts[model] = round(variants["skill"] - variants["baseline"], 4)
    return {"cells": out, "lift": lifts}
