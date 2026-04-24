"""Worker routes for KG generation."""

import asyncio
import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db.init
from config import MAX_CONCURRENT_KG_BUILDS

logger = logging.getLogger(__name__)
router = APIRouter()

_kg_lock = threading.Lock()
_active_builds: dict[tuple[int, str], bool] = {}


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
    return {"status": "ok"}


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
