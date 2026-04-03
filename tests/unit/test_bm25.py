"""Unit tests for embedding/bm25.py."""

import json
import os

import pytest

from pipeline.bm25 import (
    get_index_path,
    build_bm25_index,
    save_index,
    load_index,
    search_bm25,
    build_and_save_index,
    delete_index,
    _tokenize,
)


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_preserves_words(self):
        result = _tokenize("The Quick Brown Fox")
        assert result == ["the", "quick", "brown", "fox"]


class TestGetIndexPath:
    def test_format(self):
        path = get_index_path(1, 2)
        assert path == "data/bm25/project_1_embed_2.json"

    def test_different_ids(self):
        assert get_index_path(10, 20) != get_index_path(10, 21)


class TestBuildBm25Index:
    def test_basic_build(self, sample_texts):
        index, corpus = build_bm25_index(sample_texts)
        assert index is not None
        assert len(corpus) == len(sample_texts)

    def test_corpus_is_tokenized(self, sample_texts):
        _, corpus = build_bm25_index(sample_texts)
        for tokens in corpus:
            assert isinstance(tokens, list)
            assert all(isinstance(t, str) for t in tokens)
            # All tokens should be lowercase
            assert all(t == t.lower() for t in tokens)


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path, sample_texts):
        index, corpus = build_bm25_index(sample_texts)
        metadatas = [{"chunk_id": i, "document_id": 1} for i in range(len(sample_texts))]
        path = str(tmp_path / "test_index.json")

        save_index(corpus, sample_texts, metadatas, path)
        loaded_index, loaded_texts, loaded_meta = load_index(path)

        assert loaded_index is not None
        assert loaded_texts == sample_texts
        assert loaded_meta == metadatas

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_index(str(tmp_path / "nope.json"))

    def test_empty_corpus_returns_none_index(self, tmp_path):
        path = str(tmp_path / "empty.json")
        save_index([], [], [], path)
        index, texts, meta = load_index(path)
        assert index is None
        assert texts == []
        assert meta == []

    def test_atomic_write_creates_file(self, tmp_path):
        path = str(tmp_path / "atomic.json")
        save_index([["a"]], ["a"], [{}], path)
        assert os.path.exists(path)
        # Verify valid JSON
        with open(path) as f:
            data = json.load(f)
        assert "tokenized_corpus" in data


class TestSearchBm25:
    def test_returns_results(self, sample_texts):
        index, corpus = build_bm25_index(sample_texts)
        metadatas = [{"chunk_id": i, "document_id": 1} for i in range(len(sample_texts))]
        results = search_bm25(index, sample_texts, metadatas, "machine learning", top_k=2)
        assert len(results) > 0
        assert results[0]["score"] > 0

    def test_result_structure(self, sample_texts):
        index, _ = build_bm25_index(sample_texts)
        metadatas = [{"chunk_id": i, "document_id": 1} for i in range(len(sample_texts))]
        results = search_bm25(index, sample_texts, metadatas, "fox")
        for r in results:
            assert "content" in r
            assert "score" in r
            assert "chunk_id" in r
            assert "document_id" in r

    def test_none_index_returns_empty(self):
        results = search_bm25(None, [], [], "query")
        assert results == []

    def test_top_k_respected(self, sample_texts):
        index, _ = build_bm25_index(sample_texts)
        metadatas = [{"chunk_id": i, "document_id": 1} for i in range(len(sample_texts))]
        results = search_bm25(index, sample_texts, metadatas, "test", top_k=1)
        assert len(results) <= 1

    def test_zero_score_results_excluded(self):
        texts = ["alpha beta", "gamma delta"]
        index, _ = build_bm25_index(texts)
        metadatas = [{"chunk_id": 0}, {"chunk_id": 1}]
        # Query for something only in first text
        results = search_bm25(index, texts, metadatas, "alpha", top_k=5)
        for r in results:
            assert r["score"] > 0


class TestBuildAndSave:
    def test_build_and_save(self, tmp_path, sample_texts):
        metadatas = [{"chunk_id": i} for i in range(len(sample_texts))]
        path = str(tmp_path / "built.json")
        build_and_save_index(sample_texts, metadatas, path)
        assert os.path.exists(path)

    def test_empty_texts(self, tmp_path):
        path = str(tmp_path / "empty.json")
        build_and_save_index([], [], path)
        index, texts, meta = load_index(path)
        assert index is None


class TestDeleteIndex:
    def test_delete_existing(self, tmp_path):
        path = str(tmp_path / "to_delete.json")
        with open(path, "w") as f:
            f.write("{}")
        delete_index(path)
        assert not os.path.exists(path)

    def test_delete_nonexistent_no_error(self, tmp_path):
        delete_index(str(tmp_path / "nope.json"))  # Should not raise
