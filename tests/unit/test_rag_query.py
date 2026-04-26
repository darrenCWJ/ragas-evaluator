"""Unit tests for rag/query.py."""

import json

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import HTTPException

from pipeline.rag import (
    _build_context_text,
    _truncate_contexts,
    single_shot_query,
    multi_step_query,
    CONTEXT_CHAR_BUDGET,
)


class TestBuildContextText:
    def test_basic_format(self):
        contexts = [
            {"content": "First context"},
            {"content": "Second context"},
        ]
        result = _build_context_text(contexts)
        assert "[1] First context" in result
        assert "[2] Second context" in result

    def test_empty_contexts(self):
        assert _build_context_text([]) == ""

    def test_numbering(self):
        contexts = [{"content": f"ctx_{i}"} for i in range(5)]
        result = _build_context_text(contexts)
        for i in range(1, 6):
            assert f"[{i}]" in result


class TestTruncateContexts:
    def test_no_truncation_under_budget(self):
        contexts = [{"content": "short"}]
        result = _truncate_contexts(contexts, "system", "query")
        assert result == contexts

    def test_truncates_when_over_budget(self):
        # Create contexts that exceed the budget
        big_content = "x" * (CONTEXT_CHAR_BUDGET // 2)
        contexts = [
            {"content": big_content},
            {"content": big_content},
            {"content": big_content},
        ]
        result = _truncate_contexts(contexts, "system prompt", "query")
        assert len(result) < len(contexts)

    def test_drops_from_end(self):
        big_content = "x" * (CONTEXT_CHAR_BUDGET // 2)
        contexts = [
            {"content": "first " + big_content},
            {"content": "second " + big_content},
        ]
        result = _truncate_contexts(contexts, "s", "q")
        # Should keep first, drop second
        assert len(result) == 1
        assert "first" in result[0]["content"]


def _make_config_row(
    search_type="dense",
    llm_model="gpt-4o-mini",
    system_prompt=None,
    top_k=5,
    llm_params_json=None,
    embedding_config_id=1,
    project_id=1,
    sparse_config_id=None,
    alpha=None,
    max_steps=3,
    reranker_model=None,
    reranker_top_k=None,
):
    """Create a mock config row dict that behaves like sqlite3.Row."""
    data = {
        "search_type": search_type,
        "llm_model": llm_model,
        "system_prompt": system_prompt,
        "top_k": top_k,
        "llm_params_json": llm_params_json,
        "embedding_config_id": embedding_config_id,
        "project_id": project_id,
        "sparse_config_id": sparse_config_id,
        "alpha": alpha,
        "max_steps": max_steps,
        "reranker_model": reranker_model,
        "reranker_top_k": reranker_top_k,
    }
    return data


class TestRetrieveDense:
    async def test_retrieves_and_formats(self):
        from pipeline.rag import _retrieve_dense

        config = _make_config_row(embedding_config_id=1, project_id=1, top_k=3)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {
            "type": "dense_openai",
            "model_name": "text-embedding-3-small",
            "params_json": "{}",
        }

        raw_results = [
            {"content": "doc1", "metadata": {"chunk_id": 1, "document_id": 1}, "distance": 0.1},
            {"content": "doc2", "metadata": {"chunk_id": 2, "document_id": 1}, "distance": 0.5},
        ]

        with patch("pipeline.rag.embed_query_dispatch", new_callable=AsyncMock, return_value=[0.1, 0.2]):
            with patch("pipeline.rag.vector_search", return_value=raw_results):
                results = await _retrieve_dense("test query", config, mock_conn)

        assert len(results) == 2
        assert results[0]["content"] == "doc1"
        assert results[0]["score"] == pytest.approx(1.0 / 1.1, rel=1e-3)
        assert results[0]["chunk_id"] == 1


class TestRetrieveSparse:
    async def test_retrieves_from_bm25(self):
        from pipeline.rag import _retrieve_sparse

        config = _make_config_row(search_type="sparse", embedding_config_id=5, project_id=1)
        mock_conn = MagicMock()

        bm25_results = [
            {"content": "sparse doc", "score": 1.5, "chunk_id": 10, "document_id": 1},
        ]

        with patch("pipeline.rag.load_index", return_value=(MagicMock(), ["text"], [{}])):
            with patch("pipeline.rag.search_bm25", return_value=bm25_results):
                results = await _retrieve_sparse("query", config, mock_conn)

        assert len(results) == 1
        assert results[0]["content"] == "sparse doc"

    async def test_file_not_found_returns_empty(self):
        from pipeline.rag import _retrieve_sparse

        config = _make_config_row(search_type="sparse", embedding_config_id=5, project_id=1)
        mock_conn = MagicMock()

        with patch("pipeline.rag.load_index", side_effect=FileNotFoundError):
            results = await _retrieve_sparse("query", config, mock_conn)

        assert results == []


class TestRetrieveHybrid:
    async def test_merges_dense_and_sparse(self):
        from pipeline.rag import _retrieve_hybrid

        config = _make_config_row(
            search_type="hybrid",
            embedding_config_id=1,
            sparse_config_id=2,
            alpha=0.7,
            project_id=1,
            top_k=5,
        )
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {
            "type": "dense_openai",
            "model_name": "model",
            "params_json": "{}",
        }

        dense_raw = [
            {"content": "dense1", "metadata": {"chunk_id": 1, "document_id": 1}, "distance": 0.1},
        ]
        sparse_results = [
            {"content": "sparse1", "score": 1.0, "chunk_id": 2, "document_id": 1},
        ]

        with patch("pipeline.rag.embed_query_dispatch", new_callable=AsyncMock, return_value=[0.1]):
            with patch("pipeline.rag.vector_search", return_value=dense_raw):
                with patch("pipeline.rag.load_index", return_value=(MagicMock(), ["t"], [{}])):
                    with patch("pipeline.rag.search_bm25", return_value=sparse_results):
                        results = await _retrieve_hybrid("query", config, mock_conn)

        assert len(results) == 2
        # Both chunks should be present
        chunk_ids = {r["chunk_id"] for r in results}
        assert chunk_ids == {1, 2}
        # Scores should be positive
        for r in results:
            assert r["score"] > 0


class TestSingleShotQuery:
    async def test_no_contexts_returns_message(self):
        config = _make_config_row()
        mock_conn = MagicMock()

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=[]):
            result = await single_shot_query("test query", config, mock_conn)

        assert "No relevant contexts" in result["answer"]
        assert result["contexts"] == []
        assert result["model"] == "gpt-4o-mini"

    async def test_dense_search_success(self):
        config = _make_config_row()
        mock_conn = MagicMock()
        contexts = [
            {"content": "Answer is 42", "score": 0.9, "chunk_id": 1, "document_id": 1},
        ]

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=contexts):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = {
                    "content": "The answer is 42.",
                    "usage": {"prompt_tokens": 50, "completion_tokens": 10},
                }
                result = await single_shot_query("What is the answer?", config, mock_conn)

        assert result["answer"] == "The answer is 42."
        assert len(result["contexts"]) == 1
        assert result["usage"]["prompt_tokens"] == 50

    async def test_sparse_search_dispatches(self):
        config = _make_config_row(search_type="sparse")
        mock_conn = MagicMock()

        with patch("pipeline.rag._retrieve_sparse", new_callable=AsyncMock, return_value=[]):
            result = await single_shot_query("query", config, mock_conn)
        assert "No relevant contexts" in result["answer"]

    async def test_hybrid_search_dispatches(self):
        config = _make_config_row(search_type="hybrid", sparse_config_id=2, alpha=0.5)
        mock_conn = MagicMock()

        with patch("pipeline.rag._retrieve_hybrid", new_callable=AsyncMock, return_value=[]):
            result = await single_shot_query("query", config, mock_conn)
        assert "No relevant contexts" in result["answer"]

    async def test_unknown_search_type_raises(self):
        config = _make_config_row(search_type="quantum")
        mock_conn = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await single_shot_query("query", config, mock_conn)
        assert exc_info.value.status_code == 400

    async def test_custom_system_prompt(self):
        config = _make_config_row(system_prompt="You are a pirate.")
        mock_conn = MagicMock()
        contexts = [{"content": "data", "score": 0.5, "chunk_id": 1, "document_id": 1}]

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=contexts):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = {"content": "Arr!", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
                await single_shot_query("query", config, mock_conn)

        call_args = mock_llm.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0]["content"] == "You are a pirate."

    async def test_llm_params_forwarded(self):
        config = _make_config_row(llm_params_json='{"temperature": 0.2}')
        mock_conn = MagicMock()
        contexts = [{"content": "data", "score": 0.5, "chunk_id": 1, "document_id": 1}]

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=contexts):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = {"content": "ok", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
                await single_shot_query("query", config, mock_conn)

        call_args = mock_llm.call_args
        assert call_args.kwargs["params"] == {"temperature": 0.2}


class TestMultiStepQuery:
    async def test_no_contexts_returns_message(self):
        config = _make_config_row(max_steps=2)
        mock_conn = MagicMock()

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=[]):
            result = await multi_step_query("query", config, mock_conn)

        assert "No relevant contexts" in result["answer"]
        assert result["response_mode"] == "multi_step"
        assert len(result["steps"]) == 1

    async def test_sufficient_on_first_step(self):
        config = _make_config_row(max_steps=3)
        mock_conn = MagicMock()
        contexts = [{"content": "answer", "score": 0.9, "chunk_id": 1, "document_id": 1}]

        gap_response = json.dumps({"sufficient": True, "reasoning": "All good", "refined_query": None})

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=contexts):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                # First call: gap analysis, Second call: synthesis
                mock_llm.side_effect = [
                    {"content": gap_response, "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                    {"content": "Final answer.", "usage": {"prompt_tokens": 20, "completion_tokens": 10}},
                ]
                result = await multi_step_query("query", config, mock_conn)

        assert result["answer"] == "Final answer."
        assert result["response_mode"] == "multi_step"
        assert len(result["steps"]) == 1
        assert result["steps"][0]["sufficient"] is True
        # Token accumulation
        assert result["usage"]["prompt_tokens"] == 30
        assert result["usage"]["completion_tokens"] == 15

    async def test_multi_step_with_refinement(self):
        config = _make_config_row(max_steps=3)
        mock_conn = MagicMock()

        step1_contexts = [{"content": "partial", "score": 0.8, "chunk_id": 1, "document_id": 1}]
        step2_contexts = [{"content": "more info", "score": 0.7, "chunk_id": 2, "document_id": 1}]

        gap1 = json.dumps({"sufficient": False, "reasoning": "Need more", "refined_query": "refined"})
        gap2 = json.dumps({"sufficient": True, "reasoning": "Got it", "refined_query": None})

        call_count = 0

        async def mock_retrieve(query, config_row, conn):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return step1_contexts
            return step2_contexts

        with patch("pipeline.rag._retrieve_dense", side_effect=mock_retrieve):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = [
                    {"content": gap1, "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                    {"content": gap2, "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                    {"content": "Complete answer.", "usage": {"prompt_tokens": 30, "completion_tokens": 15}},
                ]
                result = await multi_step_query("query", config, mock_conn)

        assert result["answer"] == "Complete answer."
        assert len(result["steps"]) == 2
        assert len(result["contexts"]) == 2

    async def test_deduplication(self):
        config = _make_config_row(max_steps=2)
        mock_conn = MagicMock()

        # Same chunk_id returned twice
        contexts = [{"content": "data", "score": 0.9, "chunk_id": 1, "document_id": 1}]

        gap = json.dumps({"sufficient": False, "reasoning": "need more", "refined_query": "more"})

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=contexts):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = [
                    {"content": gap, "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
                    # Step 2: no new contexts (all deduped), goes to synthesis
                    {"content": "Answer.", "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                ]
                result = await multi_step_query("query", config, mock_conn)

        # Step 2 should report 0 new contexts
        assert result["steps"][-1]["new_contexts_count"] == 0

    async def test_gap_analysis_parse_failure(self):
        config = _make_config_row(max_steps=2)
        mock_conn = MagicMock()
        contexts = [{"content": "data", "score": 0.9, "chunk_id": 1, "document_id": 1}]

        with patch("pipeline.rag._retrieve_dense", new_callable=AsyncMock, return_value=contexts):
            with patch("pipeline.rag.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = [
                    {"content": "not valid json", "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
                    {"content": "Answer.", "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                ]
                result = await multi_step_query("query", config, mock_conn)

        # Should treat as sufficient and move to synthesis
        assert result["steps"][0]["sufficient"] is True
        assert result["answer"] == "Answer."
