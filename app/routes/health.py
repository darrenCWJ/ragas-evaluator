"""Health check route."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    try:
        import db.init

        conn = db.init.get_db()
        conn.execute("SELECT 1")
        return {"status": "ok", "version": "0.4.0-alpha", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "version": "0.4.0-alpha",
                "database": "disconnected",
            },
        )
