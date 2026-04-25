"""Health check and config defaults routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import (
    APP_VERSION,
    CONNECTOR_DEFAULT_MODELS,
    DEFAULT_EVAL_EMBEDDING,
    DEFAULT_EVAL_MODEL,
    VALID_CONNECTOR_TYPES,
)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    try:
        import db.init

        conn = db.init.get_db()
        conn.execute("SELECT 1")
        return {"status": "ok", "version": APP_VERSION, "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "version": APP_VERSION,
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
