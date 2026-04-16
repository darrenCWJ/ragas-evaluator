"""FastAPI application factory."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routes import (
    health,
    projects,
    documents,
    chunks,
    embeddings,
    rag,
    testsets,
    experiments,
    analyze,
    bot_configs,
    annotations,
    reports,
    custom_metrics,
    personas,
    multi_llm_judge,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    from db.init import init_db

    try:
        init_db()
        from config import DATABASE_PATH
        logger.info("Database initialized at %s", DATABASE_PATH)
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        sys.exit(1)
    yield
    # Cleanup: close shared HTTP clients to avoid "Event loop is closed" warnings
    from evaluation.metrics.testgen import close_openai_clients
    from pipeline.llm import close_openai_client
    await close_openai_clients()
    await close_openai_client()


def create_app() -> FastAPI:
    application = FastAPI(title="Ragas Evaluator", version="0.4.1-alpha", lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    application.include_router(health.router)
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
