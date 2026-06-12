"""Shared knowledge-graph build execution.

One implementation of the thread-mode KG build used by BOTH the main app
(app/routes/testsets.py) and the worker service (worker/routes.py) — these
previously carried near-identical copies. Runs in a daemon thread with its
own event loop, reusing the already-imported ragas stack (no subprocess
memory doubling). ``on_done`` releases the caller's active-build registry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def run_kg_build_in_thread(
    project_id: int,
    kg_source: str,
    chunk_config_id: int | None,
    overlap_max_nodes: int | None,
    fast_mode: bool,
    on_done: Callable[[], None],
) -> None:
    """Execute a KG build synchronously (call from a daemon thread)."""
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("KG build starting: project=%d source=%s", project_id, kg_source)
        from evaluation.metrics.testgen import set_progress

        set_progress(
            project_id,
            {"stage": "building_knowledge_graph", "kg_building": True},
            kg_source=kg_source,
        )

        if kg_source == "documents":
            from evaluation.metrics.testgen import build_kg_standalone_from_documents

            build_kg_standalone_from_documents(
                project_id=project_id, overlap_max_nodes=overlap_max_nodes
            )
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
        try:
            on_done()
        except Exception:
            logger.warning("KG build on_done callback failed", exc_info=True)
