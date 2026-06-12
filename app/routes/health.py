"""Health check, config defaults, and worker status routes."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import (
    CONNECTOR_DEFAULT_MODELS,
    DEFAULT_EVAL_EMBEDDING,
    DEFAULT_EVAL_MODEL,
    KG_WORKER_URLS,
    VALID_CONNECTOR_TYPES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    try:
        import db.init

        conn = db.init.get_db()
        conn.execute("SELECT 1")
        return {"status": "ok", "version": "0.4.1-alpha", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "version": "0.4.1-alpha",
                "database": "disconnected",
            },
        )


@router.get("/config/defaults")
async def config_defaults():
    """Return connector types and model defaults for frontend consumption."""
    return {
        "connector_types": sorted(VALID_CONNECTOR_TYPES),
        "default_models": CONNECTOR_DEFAULT_MODELS,
        "default_eval_model": DEFAULT_EVAL_MODEL,
        "default_eval_embedding": DEFAULT_EVAL_EMBEDDING,
    }


@router.get("/workers/status")
async def workers_status():
    """Fan out to all configured workers and aggregate their status."""
    if not KG_WORKER_URLS:
        return {"workers": [], "total_configured": 0}

    import httpx

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=5) as client:
        for url in KG_WORKER_URLS:
            try:
                resp = await client.get(f"{url}/status")
                if resp.status_code == 200:
                    data = resp.json()
                    data["url"] = url
                    data["reachable"] = True
                    results.append(data)
                else:
                    results.append({"url": url, "reachable": False, "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                logger.debug("Worker %s unreachable: %s", url, e)
                results.append({"url": url, "reachable": False, "error": str(e)})

    return {"workers": results, "total_configured": len(KG_WORKER_URLS)}


@router.post("/workers/clear-personas/{project_id}")
async def clear_worker_personas(project_id: int):
    """Clear persona generation locks on workers AND the main app."""
    from app.routes.personas import (
        _persona_task_lock,
        _persona_tasks,
        _persona_worker,
        _persona_worker_lock,
    )
    cleared = False
    with _persona_worker_lock:
        if project_id in _persona_worker:
            _persona_worker.pop(project_id)
            cleared = True
    with _persona_task_lock:
        if project_id in _persona_tasks:
            _persona_tasks.pop(project_id)
            cleared = True

    if KG_WORKER_URLS:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            for url in KG_WORKER_URLS:
                try:
                    resp = await client.post(f"{url}/clear-personas/{project_id}")
                    if resp.status_code == 200 and resp.json().get("cleared"):
                        cleared = True
                except Exception:
                    continue

    return {"cleared": cleared, "project_id": project_id}


@router.post("/workers/clear-build/{project_id}")
async def clear_worker_build(project_id: int, kg_source: str = "chunks"):
    """Proxy clear-build to the appropriate worker."""
    if not KG_WORKER_URLS:
        return {"cleared": False, "detail": "No workers configured"}

    import httpx

    async with httpx.AsyncClient(timeout=5) as client:
        for url in KG_WORKER_URLS:
            try:
                resp = await client.post(f"{url}/clear-build/{project_id}", params={"kg_source": kg_source})
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("cleared"):
                        return data
            except Exception:
                continue
    return {"cleared": False, "detail": "Task not found on any worker"}
