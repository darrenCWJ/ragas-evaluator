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
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    from db.init import init_db

    try:
        init_db()
        logger.info("Database initialized at data/ragas.db")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        sys.exit(1)
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="Ragas Evaluator", version="0.1.0", lifespan=lifespan)

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

        @application.get("/")
        async def root_redirect():
            return RedirectResponse(url="/app/setup")
    else:

        @application.get("/")
        async def root_redirect_no_build():
            return RedirectResponse(url="/app/setup")

    return application


app = create_app()
