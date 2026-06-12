"""Unit tests for bootstrap stats and deterministic retrieval diagnostics."""

import pytest

from app.routes.experiments import _retrieval_diagnostics
from evaluation.stats import bootstrap_ci, paired_delta_verdict

pytestmark = pytest.mark.unit


class TestBootstrapCI:
    def test_basic_interval_brackets_mean(self):
        ci = bootstrap_ci([0.7, 0.8, 0.9, 0.75, 0.85, 0.8, 0.7, 0.9])
        assert ci["lo"] <= ci["mean"] <= ci["hi"]
        assert ci["n"] == 8

    def test_deterministic(self):
        vals = [0.5, 0.6, 0.7, 0.8, 0.9]
        assert bootstrap_ci(vals) == bootstrap_ci(vals)

    def test_too_few_samples_mean_only(self):
        ci = bootstrap_ci([0.5, 0.7])
        assert ci["mean"] == 0.6
        assert ci["lo"] is None and ci["hi"] is None

    def test_empty_and_none_values(self):
        assert bootstrap_ci([]) is None
        assert bootstrap_ci([None, None]) is None
        assert bootstrap_ci([None, 0.5, None])["n"] == 1


class TestPairedDeltaVerdict:
    def test_clear_improvement(self):
        base = [0.5] * 10
        variant = [0.8] * 10
        v = paired_delta_verdict(base, variant)
        assert v["verdict"] == "improved"
        assert v["delta"] == pytest.approx(0.3)

    def test_clear_regression(self):
        v = paired_delta_verdict([0.8] * 10, [0.5] * 10)
        assert v["verdict"] == "regressed"

    def test_noise_is_inconclusive(self):
        # Alternating tiny changes — mean delta ~0, must not claim improvement
        base = [0.70, 0.72, 0.71, 0.69, 0.70, 0.71, 0.73, 0.70]
        variant = [0.71, 0.70, 0.72, 0.70, 0.69, 0.72, 0.71, 0.71]
        v = paired_delta_verdict(base, variant)
        assert v["verdict"] == "inconclusive"

    def test_tiny_but_consistent_delta_below_threshold(self):
        # Consistent +0.01 everywhere: CI excludes 0 but the effect is too
        # small to be meaningful — inconclusive by MIN_MEANINGFUL_DELTA.
        base = [0.70] * 10
        variant = [0.71] * 10
        v = paired_delta_verdict(base, variant)
        assert v["verdict"] == "inconclusive"

    def test_unpaired_lengths_fall_back(self):
        v = paired_delta_verdict([0.5] * 10, [0.9] * 7)
        assert v["verdict"] == "improved"

    def test_empty_returns_none(self):
        assert paired_delta_verdict([], [0.5]) is None


class TestRetrievalDiagnostics:
    CONTEXTS = [
        {"content": "a", "chunk_id": 11},
        {"content": "b", "chunk_id": 22},
        {"content": "c", "chunk_id": 33},
    ]

    def test_hit_at_rank_two(self):
        out = _retrieval_diagnostics({"source_chunk_ids": [22]}, self.CONTEXTS)
        assert out == {"retrieval_hit_rate": 1.0, "retrieval_mrr": 0.5}

    def test_hit_at_rank_one(self):
        out = _retrieval_diagnostics({"source_chunk_ids": [11, 99]}, self.CONTEXTS)
        assert out["retrieval_mrr"] == 1.0

    def test_miss(self):
        out = _retrieval_diagnostics({"source_chunk_ids": [99]}, self.CONTEXTS)
        assert out == {"retrieval_hit_rate": 0.0, "retrieval_mrr": 0.0}

    def test_no_provenance_returns_none(self):
        assert _retrieval_diagnostics({}, self.CONTEXTS) is None
        assert _retrieval_diagnostics(None, self.CONTEXTS) is None

    def test_no_chunk_ids_in_retrieved(self):
        contexts = [{"content": "a", "source": "bot"}]
        out = _retrieval_diagnostics({"source_chunk_ids": [11]}, contexts)
        assert out == {"retrieval_hit_rate": 0.0, "retrieval_mrr": 0.0}
