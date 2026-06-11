"""Run-state tracking for long-running experiment executions.

Replaces the four module-level dicts that ``app/routes/experiments.py`` used
to coordinate background tasks, SSE observers, worker delegation, and
cancellation. All state lives behind one re-entrant lock so observers always
see a consistent snapshot, and entries are timestamped so terminal states
can be evicted instead of leaking until restart.
"""

import asyncio
import copy
import threading
import time
from collections.abc import Callable

# Terminal phases may be read by late SSE reconnects for a grace period,
# then evicted.
_TERMINAL_PHASES = {"completed", "cancelled", "error"}
_TERMINAL_TTL_SECONDS = 30 * 60


class ProgressStore:
    """Thread-safe registry of per-experiment run state.

    One instance per process (module singleton ``experiment_runs`` below).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._progress: dict[int, dict] = {}
        self._touched: dict[int, float] = {}
        self._cancel_events: dict[int, asyncio.Event] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._workers: dict[int, str] = {}

    # --- progress -----------------------------------------------------------

    def set_progress(self, experiment_id: int, data: dict) -> None:
        with self._lock:
            self._progress[experiment_id] = data
            self._touched[experiment_id] = time.monotonic()

    def mutate_progress(self, experiment_id: int, fn: Callable[[dict], None]) -> bool:
        """Apply ``fn`` to the live progress dict under the lock.

        Returns False (and skips ``fn``) when no progress entry exists.
        """
        with self._lock:
            prog = self._progress.get(experiment_id)
            if prog is None:
                return False
            fn(prog)
            self._touched[experiment_id] = time.monotonic()
            return True

    def snapshot_progress(self, experiment_id: int) -> dict | None:
        """Deep-copied snapshot, safe to serialize while the run mutates state."""
        with self._lock:
            prog = self._progress.get(experiment_id)
            return copy.deepcopy(prog) if prog is not None else None

    def pop_progress(self, experiment_id: int) -> dict | None:
        with self._lock:
            self._touched.pop(experiment_id, None)
            return self._progress.pop(experiment_id, None)

    # --- cancellation ---------------------------------------------------------

    def set_cancel_event(self, experiment_id: int, event: asyncio.Event) -> None:
        with self._lock:
            self._cancel_events[experiment_id] = event

    def get_cancel_event(self, experiment_id: int) -> asyncio.Event | None:
        with self._lock:
            return self._cancel_events.get(experiment_id)

    def pop_cancel_event(self, experiment_id: int) -> asyncio.Event | None:
        with self._lock:
            return self._cancel_events.pop(experiment_id, None)

    # --- background tasks -----------------------------------------------------

    def set_task(self, experiment_id: int, task: asyncio.Task) -> None:
        with self._lock:
            self._tasks[experiment_id] = task

    def pop_task(self, experiment_id: int) -> asyncio.Task | None:
        with self._lock:
            return self._tasks.pop(experiment_id, None)

    def is_alive(self, experiment_id: int) -> bool:
        """True when a local run is tracked (cancel event or task registered)."""
        with self._lock:
            return experiment_id in self._cancel_events or experiment_id in self._tasks

    # --- worker delegation ------------------------------------------------------

    def set_worker(self, experiment_id: int, worker_url: str) -> None:
        with self._lock:
            self._workers[experiment_id] = worker_url

    def get_worker(self, experiment_id: int) -> str | None:
        with self._lock:
            return self._workers.get(experiment_id)

    def release(self, experiment_id: int) -> None:
        """Drop worker mapping and progress together (one lock acquisition)."""
        with self._lock:
            self._workers.pop(experiment_id, None)
            self._progress.pop(experiment_id, None)
            self._touched.pop(experiment_id, None)

    # --- eviction ----------------------------------------------------------------

    def evict_stale(self) -> int:
        """Remove terminal-phase progress entries older than the TTL.

        Prevents the registry growing without bound when clients never
        observe a finished run (the old behavior leaked these until restart).
        """
        cutoff = time.monotonic() - _TERMINAL_TTL_SECONDS
        evicted = 0
        with self._lock:
            for eid in list(self._progress):
                prog = self._progress[eid]
                touched = self._touched.get(eid, 0.0)
                if prog.get("phase") in _TERMINAL_PHASES and touched < cutoff:
                    self._progress.pop(eid, None)
                    self._touched.pop(eid, None)
                    self._workers.pop(eid, None)
                    evicted += 1
        return evicted


experiment_runs = ProgressStore()
