"""Unit tests for embedding/vectorstore.py."""

import sys

import pytest
from unittest.mock import patch, MagicMock

from pipeline.vectorstore import (
    get_or_create_collection,
    upsert_embeddings,
    search,
    delete_collection,
)


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the module-level client before each test."""
    vs = sys.modules["pipeline.vectorstore"]
    original = vs._client
    vs._client = None
    yield
    vs._client = original


@pytest.fixture
def mock_chromadb():
    """Mock the chromadb client and collections."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_client.get_collection.return_value = mock_collection

    with patch("pipeline.vectorstore.chromadb.PersistentClient", return_value=mock_client):
        with patch("pipeline.vectorstore.Path.mkdir"):
            yield mock_client, mock_collection


class TestGetOrCreateCollection:
    def test_returns_collection(self, mock_chromadb):
        client, collection = mock_chromadb
        result = get_or_create_collection("test_collection")
        client.get_or_create_collection.assert_called_once_with(name="test_collection")
        assert result == collection


class TestUpsertEmbeddings:
    def test_calls_upsert(self, mock_chromadb):
        _, collection = mock_chromadb
        upsert_embeddings(
            "test_col",
            ids=["id1", "id2"],
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            documents=["doc1", "doc2"],
            metadatas=[{"k": "v1"}, {"k": "v2"}],
        )
        collection.upsert.assert_called_once_with(
            ids=["id1", "id2"],
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            documents=["doc1", "doc2"],
            metadatas=[{"k": "v1"}, {"k": "v2"}],
        )


class TestSearch:
    def test_returns_results(self, mock_chromadb):
        client, collection = mock_chromadb
        collection.count.return_value = 2
        collection.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"chunk_id": 1}, {"chunk_id": 2}]],
            "distances": [[0.1, 0.5]],
        }

        results = search("test_col", [0.1, 0.2], top_k=5)
        assert len(results) == 2
        assert results[0]["content"] == "doc1"
        assert results[0]["metadata"] == {"chunk_id": 1}
        assert results[0]["distance"] == 0.1

    def test_empty_collection(self, mock_chromadb):
        _, collection = mock_chromadb
        collection.count.return_value = 0
        results = search("test_col", [0.1])
        assert results == []

    def test_collection_not_found(self, mock_chromadb):
        client, _ = mock_chromadb
        client.get_collection.side_effect = Exception("Collection not found")
        results = search("nonexistent", [0.1])
        assert results == []

    def test_top_k_capped_to_collection_count(self, mock_chromadb):
        _, collection = mock_chromadb
        collection.count.return_value = 1
        collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["doc1"]],
            "metadatas": [[{}]],
            "distances": [[0.1]],
        }
        search("test_col", [0.1], top_k=100)
        collection.query.assert_called_once_with(
            query_embeddings=[[0.1]],
            n_results=1,
        )


class TestDeleteCollection:
    def test_deletes_existing(self, mock_chromadb):
        client, _ = mock_chromadb
        delete_collection("test_col")
        client.delete_collection.assert_called_once_with(name="test_col")

    def test_nonexistent_no_error(self, mock_chromadb):
        client, _ = mock_chromadb
        client.delete_collection.side_effect = Exception("does not exist")
        delete_collection("nonexistent")  # Should not raise

    def test_unexpected_error_raises(self, mock_chromadb):
        client, _ = mock_chromadb
        client.delete_collection.side_effect = RuntimeError("disk failure")
        with pytest.raises(RuntimeError, match="disk failure"):
            delete_collection("test_col")
