"""Unit tests for retrieval upgrades: query expansion, RRF fusion,
score-threshold and MMR post-filters, and KG-assisted expansion."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from pipeline import kg_retrieval
from pipeline.rag import (
    _apply_score_threshold,
    _expand_queries,
    _mmr_select,
    _retrieve_enhanced,
    _rrf_fuse,
)

pytestmark = pytest.mark.unit


def _llm_result(content: str) -> dict:
    return {"content": content, "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


class _EmptyCursor:
    @staticmethod
    def fetchall():
        return []


class FakeConn:
    """Minimal conn whose every query returns no rows (no parent metadata)."""

    def execute(self, *_args, **_kwargs):
        return _EmptyCursor()


class TestExpandQueries:
    async def test_no_expansion_configured(self):
        queries, usage = await _expand_queries("what is rag?", {"query_expansion": None})
        assert queries == ["what is rag?"]
        assert usage == {"prompt_tokens": 0, "completion_tokens": 0}

    async def test_multi_query_adds_alternatives(self):
        cfg = {
            "query_expansion": "multi_query",
            "num_expansions": 2,
            "llm_model": "gpt-test",
            "llm_params_json": None,
        }
        mock = AsyncMock(return_value=_llm_result("1. how does rag work\n2. rag explained\n3. extra"))
        with patch("pipeline.rag.chat_completion", mock):
            queries, usage = await _expand_queries("what is rag?", cfg)

        assert queries[0] == "what is rag?"
        assert queries[1:] == ["how does rag work", "rag explained"]  # capped at 2
        assert usage == {"prompt_tokens": 11, "completion_tokens": 7}

    async def test_hyde_replaces_query_with_passage(self):
        cfg = {"query_expansion": "hyde", "llm_model": "gpt-test", "llm_params_json": None}
        mock = AsyncMock(return_value=_llm_result("RAG retrieves documents and grounds answers."))
        with patch("pipeline.rag.chat_completion", mock):
            queries, usage = await _expand_queries("what is rag?", cfg)

        assert queries == ["RAG retrieves documents and grounds answers."]
        assert usage["prompt_tokens"] == 11

    async def test_expansion_failure_falls_back_to_original(self):
        cfg = {"query_expansion": "multi_query", "llm_model": "gpt-test", "llm_params_json": None}
        mock = AsyncMock(side_effect=RuntimeError("rate limited"))
        with patch("pipeline.rag.chat_completion", mock):
            queries, _ = await _expand_queries("what is rag?", cfg)
        assert queries == ["what is rag?"]


class TestRRFFuse:
    def test_overlapping_hits_rank_first(self):
        list_a = [
            {"content": "A", "chunk_id": 1, "score": 0.9},
            {"content": "B", "chunk_id": 2, "score": 0.8},
        ]
        list_b = [
            {"content": "C", "chunk_id": 3, "score": 0.7},
            {"content": "A", "chunk_id": 1, "score": 0.6},
        ]
        fused = _rrf_fuse([list_a, list_b], top_k=3)
        assert fused[0]["chunk_id"] == 1  # appears in both lists
        assert {c["chunk_id"] for c in fused} == {1, 2, 3}

    def test_top_k_cut(self):
        lists = [[{"content": f"c{i}", "chunk_id": i, "score": 1.0} for i in range(10)]]
        assert len(_rrf_fuse(lists, top_k=4)) == 4

    def test_content_key_when_chunk_id_missing(self):
        list_a = [{"content": "same text", "chunk_id": None, "score": 0.9}]
        list_b = [{"content": "same text", "chunk_id": None, "score": 0.8}]
        fused = _rrf_fuse([list_a, list_b], top_k=5)
        assert len(fused) == 1


class TestScoreThreshold:
    CONTEXTS = [
        {"content": "good", "score": 0.8},
        {"content": "weak", "score": 0.1},
        {"content": "unscored", "score": None},
    ]

    def test_none_threshold_passthrough(self):
        assert _apply_score_threshold(self.CONTEXTS, None) == self.CONTEXTS

    def test_drops_below_threshold_keeps_unscored(self):
        kept = _apply_score_threshold(self.CONTEXTS, 0.5)
        assert [c["content"] for c in kept] == ["good", "unscored"]

    def test_can_drop_everything(self):
        assert _apply_score_threshold([{"content": "weak", "score": 0.1}], 0.5) == []


class TestMMRSelect:
    def test_passthrough_when_under_top_k(self):
        contexts = [{"content": "a b c", "score": 0.9}]
        assert _mmr_select(contexts, top_k=5, lam=0.5) == contexts

    def test_prefers_diverse_over_near_duplicate(self):
        contexts = [
            {"content": "alpha beta gamma delta", "score": 0.99},
            {"content": "alpha beta gamma delta epsilon", "score": 0.98},  # near-dup of #1
            {"content": "totally different words here", "score": 0.50},
        ]
        selected = _mmr_select(contexts, top_k=2, lam=0.5)
        assert selected[0]["content"] == "alpha beta gamma delta"
        assert selected[1]["content"] == "totally different words here"

    def test_lambda_one_is_pure_relevance(self):
        contexts = [
            {"content": "alpha beta gamma", "score": 0.9},
            {"content": "alpha beta gamma extra", "score": 0.8},
            {"content": "different things", "score": 0.1},
        ]
        selected = _mmr_select(contexts, top_k=2, lam=1.0)
        assert [c["score"] for c in selected] == [0.9, 0.8]


_KG_JSON = json.dumps(
    {
        "nodes": [
            {"id": "n1", "type": "CHUNK", "properties": {"page_content": "chunk one text"}},
            {"id": "n2", "type": "CHUNK", "properties": {"page_content": "chunk two text"}},
            {"id": "n3", "type": "CHUNK", "properties": {"page_content": "chunk three text"}},
            {"id": "n4", "type": "CHUNK", "properties": {"page_content": ""}},
        ],
        "relationships": [
            {"source": "n1", "target": "n2", "properties": {"summary_similarity": 0.9}},
            {"source": {"id": "n1"}, "target": {"id": "n3"}, "properties": {"score": 0.4}},
        ],
    }
)


class TestKGIndex:
    def test_build_and_neighbour_ordering(self):
        index = kg_retrieval.build_index(7, _KG_JSON)
        node = index.node_for_content("  chunk one text ")
        assert node == "n1"
        # n2 (0.9) ranks above n3 (0.4); empty-content n4 is excluded entirely.
        assert index.neighbour_contents("n1") == ["chunk two text", "chunk three text"]

    def test_compressed_json_roundtrip(self):
        import base64
        import zlib

        compressed = "zlib64:" + base64.b64encode(
            zlib.compress(_KG_JSON.encode("utf-8"))
        ).decode("ascii")
        index = kg_retrieval.build_index(8, compressed)
        assert index.node_for_content("chunk two text") == "n2"

    def test_select_neighbours_dedupes_and_caps(self):
        index = kg_retrieval.build_index(9, _KG_JSON)
        contexts = [
            {"content": "chunk one text", "score": 0.9, "chunk_id": 1},
            {"content": "chunk two text", "score": 0.8, "chunk_id": 2},  # already retrieved
        ]
        extras = kg_retrieval.select_neighbours(index, contexts, max_extra=5)
        # n2 is already in the context list; only n3 qualifies.
        assert [e["content"] for e in extras] == ["chunk three text"]
        assert extras[0]["kg_expanded"] is True
        assert extras[0]["score"] is None

        assert kg_retrieval.select_neighbours(index, contexts, max_extra=0) == []

    def test_cache_round_trip(self):
        index = kg_retrieval.build_index(11, _KG_JSON)
        kg_retrieval.cache_index(index)
        assert kg_retrieval.get_cached_index(11) is index
        assert kg_retrieval.get_cached_index(12) is None
        assert kg_retrieval.release_index() == 1
        assert kg_retrieval.get_cached_index(11) is None


class TestRetrieveEnhanced:
    BASE_CFG = {
        "search_type": "dense",
        "top_k": 2,
        "llm_model": "gpt-test",
        "llm_params_json": None,
        "query_expansion": None,
        "num_expansions": None,
        "score_threshold": None,
        "mmr_lambda": None,
        "kg_expansion": 0,
        "project_id": 1,
        "chunk_config_id": None,
    }

    async def test_caps_to_top_k_and_skips_parent_pass_without_ids(self):
        hits = [{"content": f"c{i}", "score": 1.0 - i / 10, "chunk_id": None} for i in range(5)]
        with patch("pipeline.rag._dispatch_retrieve", AsyncMock(return_value=hits)):
            contexts, usage = await _retrieve_enhanced("q", self.BASE_CFG, conn=None)
        assert len(contexts) == 2
        assert usage == {"prompt_tokens": 0, "completion_tokens": 0}

    async def test_mmr_over_fetches_candidates(self):
        cfg = {**self.BASE_CFG, "mmr_lambda": 0.5}
        captured = {}

        async def fake_dispatch(query, config_row, conn):
            captured["fetch_k"] = config_row["top_k"]
            return [
                {"content": f"word{i} unique{i}", "score": 1.0 - i / 10, "chunk_id": None}
                for i in range(6)
            ]

        with patch("pipeline.rag._dispatch_retrieve", fake_dispatch):
            contexts, _ = await _retrieve_enhanced("q", cfg, conn=None)

        assert captured["fetch_k"] == 6  # top_k 2 × multiplier 3
        assert len(contexts) == 2

    async def test_threshold_applied_before_cut(self):
        cfg = {**self.BASE_CFG, "score_threshold": 0.5}
        hits = [
            {"content": "good", "score": 0.9, "chunk_id": None},
            {"content": "weak", "score": 0.2, "chunk_id": None},
        ]
        with patch("pipeline.rag._dispatch_retrieve", AsyncMock(return_value=hits)):
            contexts, _ = await _retrieve_enhanced("q", cfg, conn=None)
        assert [c["content"] for c in contexts] == ["good"]

    async def test_multi_query_fuses_results(self):
        cfg = {**self.BASE_CFG, "query_expansion": "multi_query", "num_expansions": 1}

        async def fake_dispatch(query, config_row, conn):
            if query == "q":
                return [{"content": "A", "chunk_id": 1, "score": 0.9}]
            return [{"content": "B", "chunk_id": 2, "score": 0.9}]

        llm = AsyncMock(return_value=_llm_result("alternative phrasing"))
        with (
            patch("pipeline.rag.chat_completion", llm),
            patch("pipeline.rag._dispatch_retrieve", fake_dispatch),
        ):
            contexts, usage = await _retrieve_enhanced("q", cfg, conn=FakeConn())

        assert {c["chunk_id"] for c in contexts} == {1, 2}
        assert usage["prompt_tokens"] == 11
