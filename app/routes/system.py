"""System maintenance routes — reclaim RAM and disk on demand."""

import gc
import logging
import sys

from fastapi import APIRouter
from pydantic import BaseModel

import db.init
from config import DATABASE_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["system"])


class MaintenanceRequest(BaseModel):
    vacuum: bool = False


def _db_size_bytes() -> int | str:
    """Size of the SQLite database file in bytes, or 'postgres' when on PG."""
    if db.init._USE_PG:
        return "postgres"
    try:
        return DATABASE_PATH.stat().st_size
    except OSError as exc:
        logger.warning("Could not stat database file %s: %s", DATABASE_PATH, exc)
        return 0


def _release_process_memory() -> None:
    """Force garbage collection and release freed memory back to the OS.

    Same pattern as ``evaluation.metrics.testgen._release_memory`` — duplicated
    here so maintenance never has to import the heavy ragas module tree.
    """
    gc.collect()
    if sys.platform == "linux":
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass


@router.post("/system/maintenance")
async def run_maintenance(req: MaintenanceRequest) -> dict:
    """Reclaim RAM and disk: WAL checkpoint, optional VACUUM, cache eviction.

    Every step is best-effort — a failure is reported in the response but
    does not abort the remaining steps.
    """
    result: dict = {"db_size_before": _db_size_bytes()}
    is_sqlite = not db.init._USE_PG

    # Step: WAL checkpoint (SQLite only) — truncates the -wal file
    if is_sqlite:
        try:
            conn = db.init.get_db()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            result["wal_checkpoint"] = "ok"
        except Exception as exc:
            logger.warning("Maintenance: wal_checkpoint failed: %s", exc)
            result["wal_checkpoint"] = f"error: {exc}"
    else:
        result["wal_checkpoint"] = "skipped (postgres)"

    # Step: VACUUM (SQLite only, opt-in) — must run outside a transaction
    if is_sqlite and req.vacuum:
        try:
            conn = db.init.get_db()
            conn.commit()  # close any implicit transaction first
            conn.execute("VACUUM")
            result["vacuum"] = "ok"
        except Exception as exc:
            logger.warning("Maintenance: VACUUM failed: %s", exc)
            result["vacuum"] = f"error: {exc}"
    else:
        result["vacuum"] = "skipped" if is_sqlite else "skipped (postgres)"

    # Step: evict terminal experiment progress entries
    try:
        from app.services.progress import experiment_runs
        result["progress_evicted"] = experiment_runs.evict_stale()
    except Exception as exc:
        logger.warning("Maintenance: progress eviction failed: %s", exc)
        result["progress_evicted"] = f"error: {exc}"

    # Step: release cached cross-encoder models
    try:
        from pipeline.reranker import release_models as _release_ce_models
        result["reranker_models_released"] = _release_ce_models()
    except Exception as exc:
        logger.warning("Maintenance: reranker cache release failed: %s", exc)
        result["reranker_models_released"] = f"error: {exc}"

    # Step: release cached sentence-transformers models
    try:
        from pipeline.embedding import release_models as _release_st_models
        result["embedding_models_released"] = _release_st_models()
    except Exception as exc:
        logger.warning("Maintenance: embedding cache release failed: %s", exc)
        result["embedding_models_released"] = f"error: {exc}"

    # Step: GC + malloc_trim
    try:
        _release_process_memory()
        result["memory_released"] = "ok"
    except Exception as exc:
        logger.warning("Maintenance: memory release failed: %s", exc)
        result["memory_released"] = f"error: {exc}"

    result["db_size_after"] = _db_size_bytes()
    return result
