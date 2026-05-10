"""Worker routes for KG generation and persona generation."""

import asyncio
import logging
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db.init
from config import MAX_CONCURRENT_KG_BUILDS, MAX_CONCURRENT_PERSONA_BUILDS

logger = logging.getLogger(__name__)
router = APIRouter()

_kg_lock = threading.Lock()
_active_builds: dict[tuple[int, str], bool] = {}

_persona_lock = threading.Lock()
_active_persona_builds: dict[int, dict] = {}


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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("KG build starting: project=%d source=%s", project_id, kg_source)
        from evaluation.metrics.testgen import set_progress, clear_progress

        set_progress(project_id, {"stage": "building_knowledge_graph", "kg_building": True}, kg_source=kg_source)

        if kg_source == "documents":
            from evaluation.metrics.testgen import build_kg_standalone_from_documents
            build_kg_standalone_from_documents(project_id=project_id, overlap_max_nodes=overlap_max_nodes)
        else:
            from evaluation.metrics.testgen import build_kg_standalone
            build_kg_standalone(
                chunk_config_id=chunk_config_id,
                project_id=project_id,
                overlap_max_nodes=overlap_max_nodes,
                fast_mode=fast_mode,
            )
        logger.info("KG build completed: project=%d source=%s", project_id, kg_source)
    except Exception as exc:
        logger.exception("KG build failed: project=%d: %s", project_id, exc)
    finally:
        from evaluation.metrics.testgen import clear_progress
        clear_progress(project_id, kg_source=kg_source)
        loop.close()
        with _kg_lock:
            _active_builds.pop((project_id, kg_source), None)


@router.get("/health")
async def health():
    import os
    try:
        import resource
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports in bytes, Linux in KB
        if os.uname().sysname == "Darwin":
            rss_mb = rss_bytes / (1024 * 1024)
        else:
            rss_mb = rss_bytes / 1024
    except Exception:
        rss_mb = None
    return {"status": "ok", "rss_mb": round(rss_mb, 1) if rss_mb else None, "active_builds": len(_active_builds)}


@router.post("/build-kg", status_code=202)
async def build_kg(req: BuildKGRequest):
    key = (req.project_id, req.kg_source)
    with _kg_lock:
        if _active_builds.get(key):
            raise HTTPException(status_code=409, detail="Build already in progress")
        if len(_active_builds) >= MAX_CONCURRENT_KG_BUILDS:
            raise HTTPException(status_code=503, detail="Worker busy — max concurrent KG builds reached, try again shortly")
        _active_builds[key] = True

    thread = threading.Thread(
        target=_run_kg_in_thread,
        args=(req.project_id, req.kg_source, req.chunk_config_id, req.overlap_max_nodes, req.fast_mode),
        daemon=True,
    )
    thread.start()
    return {"status": "building", "project_id": req.project_id, "kg_source": req.kg_source}


@router.get("/progress/{project_id}")
async def get_progress(project_id: int, kg_source: str = "chunks"):
    from evaluation.metrics.testgen import get_progress as _get_progress, get_kg_info

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
            set_progress,
            clear_progress,
            generate_personas,
            _enrich_with_question_styles,
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

        with _persona_lock:
            _active_persona_builds[project_id] = {
                **_active_persona_builds[project_id],
                "status": "completed",
                "result": result,
            }
        logger.info("Persona generation completed: project=%d, %d personas", project_id, len(result))
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
    import os
    try:
        import resource
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss_bytes / (1024 * 1024) if os.uname().sysname == "Darwin" else rss_bytes / 1024
    except Exception:
        rss_mb = None

    tasks: list[dict] = []

    with _kg_lock:
        for (pid, source), active in _active_builds.items():
            if active:
                tasks.append({"project_id": pid, "kg_source": source, "type": "kg_build"})

    with _persona_lock:
        for pid, info in _active_persona_builds.items():
            if info.get("status") == "generating":
                tasks.append({
                    "project_id": pid,
                    "type": "persona_generation",
                    "started_at": info.get("started_at"),
                    "num_personas": info.get("num_personas"),
                })

    return {
        "status": "ok",
        "rss_mb": round(rss_mb, 1) if rss_mb else None,
        "tasks": tasks,
        "active_kg_builds": sum(1 for t in tasks if t["type"] == "kg_build"),
        "active_persona_builds": sum(1 for t in tasks if t["type"] == "persona_generation"),
        "max_concurrent_kg": MAX_CONCURRENT_KG_BUILDS,
        "max_concurrent_personas": MAX_CONCURRENT_PERSONA_BUILDS,
    }
