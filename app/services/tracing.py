"""Step-level tracing for skill trials (and other multi-step pipelines).

Every trial cell records a span per phase (prepare → query → judge → persist)
with wall time and status, stored alongside the result so the UI can render a
step timeline without external services.

When the ``langfuse`` package is installed and LANGFUSE_PUBLIC_KEY /
LANGFUSE_SECRET_KEY (and optionally LANGFUSE_HOST) are set, the same spans are
ALSO exported to Langfuse for cross-run analysis. Langfuse is strictly
optional — any failure there is logged and never affects the trial.
"""

import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_langfuse_client = None
_langfuse_checked = False


def _get_langfuse():
    """Lazily build a Langfuse client when configured; None otherwise."""
    global _langfuse_client, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_client
    _langfuse_checked = True
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse()  # reads keys/host from env
        logger.info("Langfuse tracing enabled")
    except ImportError:
        logger.warning(
            "LANGFUSE_PUBLIC_KEY is set but the langfuse package is not installed — "
            "run `pip install langfuse` to enable export"
        )
    except Exception:
        logger.warning("Langfuse client initialisation failed", exc_info=True)
    return _langfuse_client


class TraceRecorder:
    """Collects timed spans for one logical operation (e.g. one trial cell)."""

    def __init__(self, name: str, metadata: dict | None = None) -> None:
        self.name = name
        self.metadata = metadata or {}
        self.spans: list[dict] = []
        self._started = time.monotonic()

    @contextmanager
    def span(self, name: str, **attrs):
        """Record a timed span. Exceptions are recorded as error status and re-raised."""
        entry = {
            "name": name,
            "offset_ms": int((time.monotonic() - self._started) * 1000),
            "status": "ok",
            **attrs,
        }
        t0 = time.monotonic()
        try:
            yield entry
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)[:500]
            raise
        finally:
            entry["duration_ms"] = int((time.monotonic() - t0) * 1000)
            self.spans.append(entry)

    def to_list(self) -> list[dict]:
        return list(self.spans)

    def export(self) -> None:
        """Best-effort export to Langfuse (no-op when not configured)."""
        client = _get_langfuse()
        if client is None:
            return
        try:
            # Langfuse v3 API; fall back to v2's trace() shape.
            if hasattr(client, "start_span"):
                root = client.start_span(name=self.name, metadata=self.metadata)
                for s in self.spans:
                    child = root.start_span(
                        name=s["name"],
                        metadata={k: v for k, v in s.items() if k not in ("name",)},
                    )
                    child.end()
                root.end()
            elif hasattr(client, "trace"):
                trace = client.trace(name=self.name, metadata=self.metadata)
                for s in self.spans:
                    trace.span(
                        name=s["name"],
                        metadata={k: v for k, v in s.items() if k not in ("name",)},
                    )
            if hasattr(client, "flush"):
                client.flush()
        except Exception:
            logger.warning("Langfuse export failed for trace '%s'", self.name, exc_info=True)
