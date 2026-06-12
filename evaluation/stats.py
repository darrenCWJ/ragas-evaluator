"""Statistical helpers — keep the app honest about small test sets.

A +0.04 delta on 30 questions is usually noise. These helpers put bootstrap
confidence intervals on aggregates and verdicts on comparisons so the UI can
say "improved" only when the data supports it.
"""

import random

# Deltas smaller than this are treated as "no change" even when the CI is
# tight — sub-2% movements are below judge reliability.
MIN_MEANINGFUL_DELTA = 0.02

_BOOTSTRAP_ITERATIONS = 1000


def bootstrap_ci(
    values: list[float], *, confidence: float = 0.95, seed: int = 0
) -> dict | None:
    """Bootstrap CI for the mean of ``values``. Deterministic via seed.

    Returns {"mean", "lo", "hi", "n"} or None when there's nothing to compute.
    """
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    n = len(clean)
    mean = sum(clean) / n
    if n < 3:
        # Too few samples for a meaningful interval — report mean only.
        return {"mean": round(mean, 4), "lo": None, "hi": None, "n": n}

    rng = random.Random(seed)
    means = sorted(
        sum(rng.choices(clean, k=n)) / n for _ in range(_BOOTSTRAP_ITERATIONS)
    )
    tail = (1.0 - confidence) / 2
    lo_idx = int(tail * _BOOTSTRAP_ITERATIONS)
    hi_idx = min(_BOOTSTRAP_ITERATIONS - 1, int((1.0 - tail) * _BOOTSTRAP_ITERATIONS))
    return {
        "mean": round(mean, 4),
        "lo": round(means[lo_idx], 4),
        "hi": round(means[hi_idx], 4),
        "n": n,
    }


def paired_delta_verdict(
    baseline: list[float], variant: list[float], *, seed: int = 0
) -> dict | None:
    """Verdict on a metric change between two experiments.

    Uses paired per-question deltas when lengths match (much tighter), else
    falls back to the difference of independent bootstrap means.

    Returns {"delta", "lo", "hi", "verdict"} with verdict one of
    improved | regressed | inconclusive.
    """
    base = [v for v in baseline if v is not None]
    var = [v for v in variant if v is not None]
    if not base or not var:
        return None

    if len(base) == len(var) and len(base) >= 3:
        diffs = [v - b for b, v in zip(base, var, strict=True)]
        ci = bootstrap_ci(diffs, seed=seed)
        delta = ci["mean"]
        lo, hi = ci["lo"], ci["hi"]
    else:
        delta = (sum(var) / len(var)) - (sum(base) / len(base))
        ci_b = bootstrap_ci(base, seed=seed)
        ci_v = bootstrap_ci(var, seed=seed + 1)
        if ci_b["lo"] is None or ci_v["lo"] is None:
            lo = hi = None
        else:
            lo = round(ci_v["lo"] - ci_b["hi"], 4)
            hi = round(ci_v["hi"] - ci_b["lo"], 4)

    if lo is None or hi is None:
        verdict = "inconclusive"
    elif lo > 0 and delta >= MIN_MEANINGFUL_DELTA:
        verdict = "improved"
    elif hi < 0 and delta <= -MIN_MEANINGFUL_DELTA:
        verdict = "regressed"
    else:
        verdict = "inconclusive"
    return {"delta": round(delta, 4), "lo": lo, "hi": hi, "verdict": verdict}
