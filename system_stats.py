"""Process memory statistics shared by the main app and worker services."""

import sys


def memory_stats() -> dict:
    """Return current and peak RSS for this process in MB (None if unavailable).

    ``rss_mb`` is the live resident set size via psutil. ``peak_rss_mb`` is the
    high-water mark from getrusage — it only ever grows, so it must never be
    presented as "current" usage.
    """
    current_mb = None
    peak_mb = None
    try:
        import psutil

        current_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes, Linux reports KB
        peak_mb = peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    except Exception:
        pass
    return {
        "rss_mb": round(current_mb, 1) if current_mb is not None else None,
        "peak_rss_mb": round(peak_mb, 1) if peak_mb is not None else None,
    }
