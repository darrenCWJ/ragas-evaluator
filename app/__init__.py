"""FastAPI application factory."""

import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.routes import (
    analyze,
    annotations,
    auth,
    bot_configs,
    chunks,
    custom_metrics,
    documents,
    embeddings,
    experiments,
    health,
    insights,
    multi_llm_judge,
    personas,
    projects,
    rag,
    reports,
    skills,
    system,
    testsets,
)
from app.services.request_context import RequestIDMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    import asyncio

    from db.init import init_db

    try:
        init_db()
        from config import DATABASE_PATH
        logger.info("Database initialized at %s", DATABASE_PATH)
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        sys.exit(1)

    # Background task: monitor worker-delegated experiments for liveness
    async def _monitor_worker_experiments():
        from app.services.progress import experiment_runs

        consecutive_failures: dict[int, int] = {}
        while True:
            await asyncio.sleep(30)
            entries = experiment_runs.delegated()
            if not entries:
                continue
            import httpx
            for eid, worker_url in entries.items():
                try:
                    async with httpx.AsyncClient(timeout=5) as client:
                        resp = await client.get(f"{worker_url}/experiment-progress/{eid}")
                    consecutive_failures.pop(eid, None)
                    if resp.status_code == 200:
                        data = resp.json()
                        if not data.get("active", True):
                            experiment_runs.release(eid)
                except Exception:
                    consecutive_failures[eid] = consecutive_failures.get(eid, 0) + 1
                    if consecutive_failures[eid] >= 3:
                        logger.warning("Worker %s unreachable for experiment %d — marking failed", worker_url, eid)
                        try:
                            import db.init
                            conn = db.init.get_db()
                            row = conn.execute(
                                "SELECT status FROM experiments WHERE id = ?", (eid,)
                            ).fetchone()
                            if row and row["status"] == "running":
                                from datetime import datetime as dt
                                conn.execute(
                                    "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
                                    (dt.now().isoformat(), eid),
                                )
                                conn.commit()
                        except Exception as _db_err:
                            logger.warning("Failed to mark experiment %d as failed: %s", eid, _db_err)
                        experiment_runs.release(eid)
                        consecutive_failures.pop(eid, None)

    monitor_task = asyncio.create_task(_monitor_worker_experiments())

    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    # Cleanup: close shared HTTP clients to avoid "Event loop is closed" warnings
    from evaluation.metrics.testgen import close_openai_clients
    from pipeline.embedding import close_openai_embed_client
    from pipeline.llm import close_anthropic_client, close_gemini_client, close_openai_client
    await close_openai_clients()
    await close_openai_client()
    await close_anthropic_client()
    await close_gemini_client()
    await close_openai_embed_client()


_RAGAS_API_KEY = os.environ.get("RAGAS_API_KEY", "")

_AUTH_EXEMPT_PREFIXES = ("/app/", "/health", "/api/auth/")

# /api/projects/{id}/...  → per-project access enforcement
_PROJECT_PATH_RE = re.compile(r"^/api/projects/(\d+)(?:/|$)")

# Login enforcement activates once any user exists. The check flips exactly
# once (users are never all deleted in normal operation), so cache the True.
_auth_active_cache = False


def _auth_is_active() -> bool:
    global _auth_active_cache
    if _auth_active_cache:
        return True
    try:
        import db.init as _db
        from app.services.auth import any_users_exist

        if any_users_exist(_db.get_db()):
            _auth_active_cache = True
    except Exception:
        logger.warning("Auth-active check failed — treating as inactive", exc_info=True)
    return _auth_active_cache


class _AuthMiddleware(BaseHTTPMiddleware):
    """Two-layer auth.

    Open mode (no registered users): legacy behavior — everything passes,
    unless RAGAS_API_KEY is set, in which case it is required as a Bearer
    token (the original deployment story).

    User mode (≥1 registered user): every non-exempt request needs a valid
    session cookie or the machine Bearer token. Project-scoped paths
    additionally require ownership/membership — admins (and the machine
    token) can access every project.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES) or path == "/":
            return await call_next(request)

        if not _auth_is_active():
            # Legacy open mode (optionally gated by the shared machine key)
            if _RAGAS_API_KEY:
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or auth[len("Bearer "):] != _RAGAS_API_KEY:
                    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return await call_next(request)

        import db.init as _db
        from app.services.auth import resolve_request_user, user_can_access_project

        conn = _db.get_db()
        user = resolve_request_user(conn, request)
        if user is None:
            return JSONResponse(status_code=401, content={"detail": "Not signed in"})

        match = _PROJECT_PATH_RE.match(path)
        if match and not user_can_access_project(conn, user, int(match.group(1))):
            return JSONResponse(
                status_code=403,
                content={"detail": "You don't have access to this project"},
            )

        request.state.user = user
        return await call_next(request)


def create_app() -> FastAPI:
    application = FastAPI(title="Tribunal — RAG Evaluator", version="0.4.1-alpha", lifespan=lifespan)

    # Middleware execution order is the reverse of registration: RequestID is
    # registered last so it runs OUTERMOST — even auth-rejected and CORS
    # responses carry a correlatable X-Request-ID.
    application.add_middleware(_AuthMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(","),
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
    )
    application.add_middleware(RequestIDMiddleware)

    # Register routers
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(projects.router)
    application.include_router(documents.router)
    application.include_router(chunks.router)
    application.include_router(embeddings.router)
    application.include_router(rag.router)
    application.include_router(testsets.router)
    application.include_router(experiments.router)
    application.include_router(analyze.router)
    application.include_router(bot_configs.router)
    application.include_router(annotations.router)
    application.include_router(reports.router)
    application.include_router(custom_metrics.router)
    application.include_router(personas.router)
    application.include_router(multi_llm_judge.router)
    application.include_router(skills.router)
    application.include_router(insights.router)
    application.include_router(system.router)

    # SPA catch-all
    _frontend_dist = Path("frontend/dist")
    if _frontend_dist.is_dir():
        application.mount(
            "/app/assets",
            StaticFiles(directory=str(_frontend_dist / "assets")),
            name="frontend-assets",
        )

        @application.get("/app/{path:path}")
        async def spa_fallback(path: str):
            return FileResponse(str(_frontend_dist / "index.html"))

    else:
        logger.warning("frontend/dist not found — SPA will not be served")

        @application.get("/app/{path:path}")
        async def spa_not_built(path: str):
            return JSONResponse(
                status_code=503,
                content={"detail": "Frontend not built. Run: cd frontend && npm run build"},
            )

    @application.get("/")
    async def root_redirect():
        return RedirectResponse(url="/app/setup")

    return application


app = create_app()
