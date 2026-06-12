"""Worker routes for KG generation and persona generation."""

import asyncio
import logging
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db.init
from config import (
    MAX_CONCURRENT_EXPERIMENTS,
    MAX_CONCURRENT_KG_BUILDS,
    MAX_CONCURRENT_PERSONA_BUILDS,
    MAX_CONCURRENT_TESTGENS,
)
from system_stats import memory_stats

logger = logging.getLogger(__name__)
router = APIRouter()

_kg_lock = threading.Lock()
_active_builds: dict[tuple[int, str], dict] = {}  # (project_id, kg_source) -> {"started_at"}

_persona_lock = threading.Lock()
_active_persona_builds: dict[int, dict] = {}

_experiment_lock = threading.Lock()
_active_experiments: dict[int, dict] = {}  # experiment_id -> {"project_id", "started_at"}

_testgen_lock = threading.Lock()
_active_testgens: dict[int, dict] = {}  # project_id -> {"test_set_id", "started_at"}


class BuildKGRequest(BaseModel):
    project_id: int
    chunk_config_id: int | None = None
    kg_source: str = "chunks"
    overlap_max_nodes: int | None = 500
    fast_mode: bool = False


def _run_kg_in_thread(
    project_id: int,
    kg_source: str,
    chunk_config_id: int | None,
    overlap_max_nodes: int | None,
    fast_mode: bool,
) -> None:
    """Thread-mode KG build (shared implementation in app.services.kg_builder)."""
    from app.services.kg_builder import run_kg_build_in_thread

    def _release() -> None:
        with _kg_lock:
            _active_builds.pop((project_id, kg_source), None)

    run_kg_build_in_thread(
        project_id, kg_source, chunk_config_id, overlap_max_nodes, fast_mode, _release
    )


@router.get("/health")
async def health():
    mem = memory_stats()
    return {"status": "ok", **mem, "active_builds": len(_active_builds)}


@router.post("/build-kg", status_code=202)
async def build_kg(req: BuildKGRequest):
    key = (req.project_id, req.kg_source)
    with _kg_lock:
        if _active_builds.get(key):
            raise HTTPException(status_code=409, detail="Build already in progress")
        if len(_active_builds) >= MAX_CONCURRENT_KG_BUILDS:
            raise HTTPException(status_code=503, detail="Worker busy — max concurrent KG builds reached, try again shortly")
        _active_builds[key] = {"started_at": time.time()}

    thread = threading.Thread(
        target=_run_kg_in_thread,
        args=(req.project_id, req.kg_source, req.chunk_config_id, req.overlap_max_nodes, req.fast_mode),
        daemon=True,
    )
    thread.start()
    return {"status": "building", "project_id": req.project_id, "kg_source": req.kg_source}


@router.get("/progress/{project_id}")
async def get_progress(project_id: int, kg_source: str = "chunks"):
    from evaluation.metrics.testgen import get_kg_info
    from evaluation.metrics.testgen import get_progress as _get_progress

    key = (project_id, kg_source)
    with _kg_lock:
        active = _active_builds.get(key, False)

    progress = _get_progress(project_id, kg_source=kg_source)
    if active:
        return {"active": True, **(progress or {"stage": "building_knowledge_graph"})}

    info = get_kg_info(project_id, kg_source=kg_source)
    if info:
        status = "completed" if info.get("is_complete") else "partial"
        return {"active": False, "status": status, **info}
    return {"active": False}


@router.delete("/kg/{project_id}", status_code=204)
async def delete_kg(project_id: int, kg_source: str = "chunks"):
    from evaluation.metrics.testgen import delete_kg_from_db
    delete_kg_from_db(project_id, kg_source=kg_source)


@router.post("/clear-build/{project_id}", status_code=200)
async def clear_stale_build(project_id: int, kg_source: str = "chunks"):
    """Clear a stale build lock left over from a crashed build."""
    key = (project_id, kg_source)
    with _kg_lock:
        was_active = _active_builds.pop(key, None)
    from evaluation.metrics.testgen import clear_progress
    clear_progress(project_id, kg_source=kg_source)
    return {"cleared": was_active is not None}


# ---------------------------------------------------------------------------
# Persona generation
# ---------------------------------------------------------------------------


class GeneratePersonasRequest(BaseModel):
    project_id: int
    chunk_config_id: int
    num_personas: int = 3


def _run_personas_in_thread(
    project_id: int,
    chunk_config_id: int,
    num_personas: int,
) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("Persona generation starting: project=%d num=%d", project_id, num_personas)
        from evaluation.metrics.testgen import (
            _enrich_with_question_styles,
            clear_progress,
            generate_personas,
            set_progress,
        )

        set_progress(project_id, {"stage": "generating_personas", "persona_generating": True}, kg_source="personas")

        conn = db.init.get_db()
        chunk_rows = conn.execute(
            "SELECT content FROM chunks WHERE chunk_config_id = ?",
            (chunk_config_id,),
        ).fetchall()
        chunks = [r["content"] for r in chunk_rows]

        if not chunks:
            raise RuntimeError(f"No chunks found for chunk_config_id={chunk_config_id}")

        personas = generate_personas(chunks=chunks, num_personas=num_personas, fast=False, project_id=project_id)
        result = _enrich_with_question_styles(personas)

        saved_count = 0
        for p in result:
            name = p.get("name", "").strip()
            role_desc = p.get("role_description", "").strip()
            if not name or not role_desc:
                continue
            conn.execute(
                "INSERT INTO personas (project_id, name, role_description, question_style) VALUES (?, ?, ?, ?)",
                (project_id, name, role_desc, p.get("question_style", "")),
            )
            saved_count += 1
        conn.commit()

        with _persona_lock:
            _active_persona_builds[project_id] = {
                **_active_persona_builds[project_id],
                "status": "completed",
                "result": result,
            }
        logger.info("Persona generation completed: project=%d, %d personas saved to DB", project_id, saved_count)
    except Exception as exc:
        logger.exception("Persona generation failed: project=%d: %s", project_id, exc)
        with _persona_lock:
            if project_id in _active_persona_builds:
                _active_persona_builds[project_id] = {
                    **_active_persona_builds[project_id],
                    "status": "error",
                    "detail": str(exc),
                }
    finally:
        from evaluation.metrics.testgen import clear_progress
        clear_progress(project_id, kg_source="personas")
        loop.close()


@router.post("/generate-personas", status_code=202)
async def generate_personas_endpoint(req: GeneratePersonasRequest):
    with _persona_lock:
        if req.project_id in _active_persona_builds and _active_persona_builds[req.project_id].get("status") == "generating":
            raise HTTPException(status_code=409, detail="Persona generation already in progress")
        active_count = sum(1 for v in _active_persona_builds.values() if v.get("status") == "generating")
        if active_count >= MAX_CONCURRENT_PERSONA_BUILDS:
            raise HTTPException(status_code=503, detail="Worker busy — max concurrent persona builds reached")
        _active_persona_builds[req.project_id] = {
            "status": "generating",
            "started_at": time.time(),
            "num_personas": req.num_personas,
            "result": None,
            "detail": None,
        }

    thread = threading.Thread(
        target=_run_personas_in_thread,
        args=(req.project_id, req.chunk_config_id, req.num_personas),
        daemon=True,
    )
    thread.start()
    return {"status": "generating", "project_id": req.project_id}


@router.get("/persona-progress/{project_id}")
async def get_persona_progress(project_id: int):
    from evaluation.metrics.testgen import get_progress as _get_progress

    with _persona_lock:
        task = _active_persona_builds.get(project_id)

    if task is None:
        return {"active": False}

    if task["status"] == "generating":
        progress = _get_progress(project_id, kg_source="personas")
        return {"active": True, **(progress or {"stage": "generating_personas"})}

    if task["status"] == "completed":
        result = task.get("result", [])
        with _persona_lock:
            _active_persona_builds.pop(project_id, None)
        return {"active": False, "status": "completed", "personas": result}

    if task["status"] == "error":
        detail = task.get("detail", "Unknown error")
        with _persona_lock:
            _active_persona_builds.pop(project_id, None)
        return {"active": False, "status": "error", "detail": detail}

    return {"active": False}


@router.post("/clear-personas/{project_id}", status_code=200)
async def clear_stale_personas(project_id: int):
    """Clear a stuck persona generation lock."""
    with _persona_lock:
        was_active = _active_persona_builds.pop(project_id, None)
    from evaluation.metrics.testgen import clear_progress
    clear_progress(project_id, kg_source="personas")
    return {"cleared": was_active is not None}


# ---------------------------------------------------------------------------
# Worker status (all active tasks)
# ---------------------------------------------------------------------------


@router.get("/status")
async def worker_status():
    """Rich status for dashboard: all active tasks with metadata."""
    from evaluation.metrics.testgen import get_progress as _testgen_progress

    mem = memory_stats()

    tasks: list[dict] = []

    with _kg_lock:
        kg_builds = {key: dict(info) for key, info in _active_builds.items() if info}
    for (pid, source), info in kg_builds.items():
        prog = _testgen_progress(pid, kg_source=source) or {}
        tasks.append({
            "project_id": pid,
            "kg_source": source,
            "type": "kg_build",
            "started_at": info.get("started_at"),
            "stage": prog.get("stage"),
            "completed_steps": prog.get("completed_steps"),
            "total_steps": prog.get("total_steps"),
            "batch_current": prog.get("batch_current"),
            "batch_total": prog.get("batch_total"),
        })

    with _persona_lock:
        for pid, info in _active_persona_builds.items():
            if info.get("status") == "generating":
                tasks.append({
                    "project_id": pid,
                    "type": "persona_generation",
                    "started_at": info.get("started_at"),
                    "num_personas": info.get("num_personas"),
                })

    from app.services.progress import experiment_runs

    with _experiment_lock:
        experiments = {eid: dict(info) for eid, info in _active_experiments.items()}
    for eid, info in experiments.items():
        prog = experiment_runs.snapshot_progress(eid) or {}
        tasks.append({
            "experiment_id": eid,
            "project_id": info.get("project_id"),
            "type": "experiment",
            "started_at": info.get("started_at"),
            "phase": prog.get("phase"),
            "current": prog.get("current"),
            "total": prog.get("total"),
        })

    with _testgen_lock:
        testgens = {pid: dict(info) for pid, info in _active_testgens.items()}
    for pid, info in testgens.items():
        prog = _testgen_progress(pid, kg_source="testset") or {}
        tasks.append({
            "project_id": pid,
            "test_set_id": info.get("test_set_id"),
            "type": "testgen",
            "started_at": info.get("started_at"),
            "stage": prog.get("stage"),
            "questions_generated": prog.get("questions_generated"),
        })

    return {
        "status": "ok",
        **mem,
        "tasks": tasks,
        "active_kg_builds": sum(1 for t in tasks if t["type"] == "kg_build"),
        "active_persona_builds": sum(1 for t in tasks if t["type"] == "persona_generation"),
        "active_experiments": sum(1 for t in tasks if t["type"] == "experiment"),
        "active_testgens": sum(1 for t in tasks if t["type"] == "testgen"),
        "max_concurrent_kg": MAX_CONCURRENT_KG_BUILDS,
        "max_concurrent_personas": MAX_CONCURRENT_PERSONA_BUILDS,
        "max_concurrent_experiments": MAX_CONCURRENT_EXPERIMENTS,
        "max_concurrent_testgens": MAX_CONCURRENT_TESTGENS,
    }


# ---------------------------------------------------------------------------
# Experiment execution (delegated from the main app)
# ---------------------------------------------------------------------------


class WorkerExperimentRequest(BaseModel):
    experiment_id: int
    project_id: int
    metrics: list[str] | None = None
    rubrics: dict[str, str] | None = None
    concurrency: int = 5
    multi_llm_judge_evaluators: int = 5
    judge_model_assignments: list[str] | None = None
    judge_temperature_assignments: list[float] | None = None


@router.post("/run-experiment", status_code=202)
async def run_experiment(req: WorkerExperimentRequest):
    """Execute an experiment on this worker.

    The main app has already validated metrics, claimed the experiment row
    (status='running'), and cleaned up partial results before delegating.
    """
    from app.models import ExperimentRunRequest
    from app.services.experiment_runner import run_experiment_background
    from app.services.progress import experiment_runs

    with _experiment_lock:
        if req.experiment_id in _active_experiments:
            raise HTTPException(status_code=409, detail="Experiment already running on this worker")
        if len(_active_experiments) >= MAX_CONCURRENT_EXPERIMENTS:
            raise HTTPException(status_code=503, detail="Worker busy — max concurrent experiments reached")
        _active_experiments[req.experiment_id] = {
            "project_id": req.project_id,
            "started_at": time.time(),
        }

    try:
        conn = db.init.get_db()
        experiment = conn.execute(
            "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
            (req.experiment_id, req.project_id),
        ).fetchone()
        if experiment is None:
            raise HTTPException(status_code=404, detail="Experiment not found")

        all_custom_rows = conn.execute(
            "SELECT * FROM custom_metrics WHERE project_id = ?", (req.project_id,)
        ).fetchall()

        run_req = ExperimentRunRequest(
            metrics=req.metrics,
            rubrics=req.rubrics,
            concurrency=req.concurrency,
            multi_llm_judge_evaluators=req.multi_llm_judge_evaluators,
            judge_model_assignments=req.judge_model_assignments,
            judge_temperature_assignments=req.judge_temperature_assignments,
        )

        cancel_event = asyncio.Event()
        experiment_runs.set_cancel_event(req.experiment_id, cancel_event)
        experiment_runs.set_progress(req.experiment_id, {
            "phase": "starting", "current": 0, "total": 0,
            "question": "", "error": None, "result_count": 0,
            "completed_items": [], "in_flight": [], "scoring_metrics": [],
        })
        task = asyncio.create_task(run_experiment_background(
            experiment_id=req.experiment_id,
            project_id=req.project_id,
            experiment=experiment,
            selected_metrics=req.metrics or [],
            all_custom_rows=all_custom_rows,
            req=run_req,
            cancel_event=cancel_event,
        ))
        experiment_runs.set_task(req.experiment_id, task)

        def _on_done(_task, eid=req.experiment_id):
            experiment_runs.pop_task(eid)
            experiment_runs.pop_cancel_event(eid)
            with _experiment_lock:
                _active_experiments.pop(eid, None)

        task.add_done_callback(_on_done)
    except HTTPException:
        with _experiment_lock:
            _active_experiments.pop(req.experiment_id, None)
        raise
    except Exception as exc:
        logger.exception("Failed to start experiment %d on worker", int(req.experiment_id))
        with _experiment_lock:
            _active_experiments.pop(req.experiment_id, None)
        raise HTTPException(status_code=500, detail=f"Failed to start experiment: {exc}") from exc

    return {"status": "running", "experiment_id": req.experiment_id}


@router.get("/experiment-progress/{experiment_id}")
async def experiment_progress(experiment_id: int):
    from app.services.progress import experiment_runs

    progress = experiment_runs.snapshot_progress(experiment_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="No active progress for this experiment")
    return progress


@router.post("/cancel-experiment/{experiment_id}")
async def cancel_experiment(experiment_id: int):
    from app.services.progress import experiment_runs

    event = experiment_runs.get_cancel_event(experiment_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Experiment not running on this worker")
    event.set()
    return {"status": "cancelling", "experiment_id": experiment_id}


# ---------------------------------------------------------------------------
# Test set generation (delegated from the main app)
# ---------------------------------------------------------------------------


class WorkerTestgenRequest(BaseModel):
    project_id: int
    test_set_id: int
    testset_size: int
    use_personas: bool = False
    num_personas: int = 3
    custom_personas: list[dict] | None = None
    query_distribution: dict[str, float] | None = None
    chunk_sample_size: int = 0
    num_workers: int = 4
    question_categories: dict[str, int] | None = None
    graph_rag_kg_source: str = "chunks"
    use_kg_as_source: bool = False
    fast_kg_mode: bool = False


def _run_testgen_in_thread(project_id: int, test_set_id: int, chunks: list[str], gen_req) -> None:
    try:
        from app.routes.testsets import _run_generation

        _run_generation(project_id, test_set_id, chunks, gen_req)
    except Exception:
        logger.exception("Test generation thread crashed: project=%d test_set=%d", project_id, test_set_id)
    finally:
        with _testgen_lock:
            _active_testgens.pop(project_id, None)


@router.post("/run-testgen", status_code=202)
async def run_testgen(req: WorkerTestgenRequest):
    """Run test set generation on this worker.

    The main app has already created the test_sets row (status='generating');
    this endpoint reconstructs the generation source and runs the generator.
    """
    from app.models import TestSetCreate
    from app.services.testset_chunks import load_generation_chunks

    with _testgen_lock:
        if req.project_id in _active_testgens:
            raise HTTPException(status_code=409, detail="Test generation already running for this project on this worker")
        if len(_active_testgens) >= MAX_CONCURRENT_TESTGENS:
            raise HTTPException(status_code=503, detail="Worker busy — max concurrent test generations reached")
        _active_testgens[req.project_id] = {
            "test_set_id": req.test_set_id,
            "started_at": time.time(),
        }

    try:
        conn = db.init.get_db()
        ts_row = conn.execute(
            "SELECT generation_config_json FROM test_sets WHERE id = ? AND project_id = ?",
            (req.test_set_id, req.project_id),
        ).fetchone()
        if ts_row is None:
            raise HTTPException(status_code=404, detail="Test set not found")

        import json as _json

        generation_config = _json.loads(ts_row["generation_config_json"] or "{}")
        gen_req = TestSetCreate(
            chunk_config_id=generation_config.get("chunk_config_id"),
            testset_size=req.testset_size,
            use_personas=req.use_personas,
            num_personas=req.num_personas,
            custom_personas=req.custom_personas,
            query_distribution=req.query_distribution,
            chunk_sample_size=req.chunk_sample_size,
            num_workers=req.num_workers,
            question_categories=req.question_categories,
            graph_rag_kg_source=req.graph_rag_kg_source,
            use_kg_as_source=req.use_kg_as_source,
            fast_kg_mode=req.fast_kg_mode,
        )

        chunks = load_generation_chunks(conn, req.project_id, gen_req)

        thread = threading.Thread(
            target=_run_testgen_in_thread,
            args=(req.project_id, req.test_set_id, chunks, gen_req),
            daemon=True,
        )
        thread.start()
    except HTTPException:
        with _testgen_lock:
            _active_testgens.pop(req.project_id, None)
        raise
    except Exception as exc:
        logger.exception("Failed to start test generation %d on worker", int(req.test_set_id))
        with _testgen_lock:
            _active_testgens.pop(req.project_id, None)
        raise HTTPException(status_code=500, detail=f"Failed to start test generation: {exc}") from exc

    return {"status": "generating", "project_id": req.project_id, "test_set_id": req.test_set_id}


@router.get("/testgen-progress/{project_id}")
async def testgen_progress(project_id: int):
    from evaluation.metrics.testgen import get_progress as _testgen_progress

    progress = _testgen_progress(project_id, kg_source="testset")
    with _testgen_lock:
        active = project_id in _active_testgens
    if progress is None and not active:
        return {"active": False}
    return {"active": True, **(progress or {})}


@router.post("/cancel-testgen/{project_id}")
async def cancel_testgen(project_id: int):
    with _testgen_lock:
        if project_id not in _active_testgens:
            raise HTTPException(status_code=404, detail="No active test generation for this project on this worker")
    from evaluation.metrics.testgen import cancel_generation

    cancel_generation(project_id)
    return {"status": "cancelling", "project_id": project_id}
