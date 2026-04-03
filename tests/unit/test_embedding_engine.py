"""Unit tests for embedding/engine.py."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from pipeline.embedding import (
    embed_texts_dispatch,
    embed_query_dispatch,
    _DISPATCH,
)


class TestEmbedTextsDispatch:
    async def test_unsupported_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported embedding type"):
            await embed_texts_dispatch(["text"], "nonexistent_type", "model", {})

    async def test_dispatches_to_openai(self):
        mock_handler = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        with patch.dict(_DISPATCH, {"dense_openai": mock_handler}):
            result = await embed_texts_dispatch(["hello"], "dense_openai", "text-embedding-3-small", {})
            mock_handler.assert_called_once_with(["hello"], "text-embedding-3-small", {})
            assert result == [[0.1, 0.2, 0.3]]

    async def test_dispatches_openai_alias(self):
        mock_handler = AsyncMock(return_value=[[0.1]])
        with patch.dict(_DISPATCH, {"openai": mock_handler}):
            await embed_texts_dispatch(["x"], "openai", "model", {})
            mock_handler.assert_called_once()

    async def test_dispatches_to_sentence_transformers(self):
        mock_handler = AsyncMock(return_value=[[0.5, 0.6]])
        with patch.dict(_DISPATCH, {"dense_sentence_transformers": mock_handler}):
            result = await embed_texts_dispatch(["hi"], "dense_sentence_transformers", "all-MiniLM-L6-v2", {})
            mock_handler.assert_called_once()
            assert result == [[0.5, 0.6]]

    async def test_dispatches_sentence_transformers_alias(self):
        mock_handler = AsyncMock(return_value=[[0.1]])
        with patch.dict(_DISPATCH, {"sentence_transformers": mock_handler}):
            await embed_texts_dispatch(["x"], "sentence_transformers", "model", {})
            mock_handler.assert_called_once()

    async def test_empty_texts_returns_empty(self):
        mock_handler = AsyncMock(return_value=[])
        with patch.dict(_DISPATCH, {"dense_openai": mock_handler}):
            result = await embed_texts_dispatch([], "dense_openai", "model", {})
            assert result == []

    async def test_all_dispatch_types_registered(self):
        expected = {"dense_openai", "openai", "dense_sentence_transformers", "sentence_transformers"}
        assert set(_DISPATCH.keys()) == expected


class TestEmbedQueryDispatch:
    async def test_returns_single_vector(self):
        mock_handler = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        with patch.dict(_DISPATCH, {"dense_openai": mock_handler}):
            result = await embed_query_dispatch("hello", "dense_openai", "model", {})
            assert result == [0.1, 0.2, 0.3]

    async def test_passes_query_as_list(self):
        mock_handler = AsyncMock(return_value=[[0.5]])
        with patch.dict(_DISPATCH, {"dense_openai": mock_handler}):
            await embed_query_dispatch("test query", "dense_openai", "model", {})
            mock_handler.assert_called_once_with(["test query"], "model", {})


class TestEmbedOpenai:
    async def test_batching(self):
        """Verify batching for >100 texts."""
        from pipeline.embedding import _embed_openai

        call_count = 0

        class FakeData:
            def __init__(self, val):
                self.embedding = [val]

        class FakeResponse:
            def __init__(self, n):
                self.data = [FakeData(0.1) for _ in range(n)]

        async def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return FakeResponse(len(kwargs["input"]))

        mock_client = MagicMock()
        mock_client.embeddings.create = fake_create

        with patch("pipeline.embedding.AsyncOpenAI", return_value=mock_client):
            texts = [f"text_{i}" for i in range(250)]
            result = await _embed_openai(texts, "model", {})
            assert len(result) == 250
            assert call_count == 3  # 100 + 100 + 50

    async def test_empty_texts_returns_empty(self):
        from pipeline.embedding import _embed_openai

        result = await _embed_openai([], "model", {})
        assert result == []


class TestEmbedSentenceTransformers:
    async def test_calls_model_encode(self):
        import numpy as np
        from pipeline.embedding import _embed_sentence_transformers

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])

        with patch("pipeline.embedding._get_st_model", return_value=mock_model):
            result = await _embed_sentence_transformers(["a", "b"], "all-MiniLM-L6-v2", {})

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    async def test_empty_returns_empty(self):
        from pipeline.embedding import _embed_sentence_transformers

        result = await _embed_sentence_transformers([], "model", {})
        assert result == []
