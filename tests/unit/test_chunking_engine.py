"""Unit tests for chunking/engine.py."""

import pytest

from pipeline.chunking import chunk_text, chunk_text_pipeline, VALID_METHODS


class TestChunkText:
    """Tests for the chunk_text dispatcher."""

    def test_empty_text_returns_empty(self):
        assert chunk_text("", "recursive", {}) == []

    def test_whitespace_only_returns_empty(self):
        assert chunk_text("   \n\t  ", "recursive", {}) == []

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="Invalid chunking method"):
            chunk_text("hello", "nonexistent", {})

    def test_valid_methods_all_return_list(self):
        text = "Hello world. This is a test paragraph with enough content to chunk."
        for method in VALID_METHODS:
            result = chunk_text(text, method, {})
            assert isinstance(result, list)
            assert all(isinstance(c, str) for c in result)

    def test_param_coercion_string_to_int(self):
        text = "A" * 200
        result = chunk_text(text, "recursive", {"chunk_size": "100"})
        assert isinstance(result, list)
        assert len(result) > 1

    def test_param_alias_parent_chunk_size(self):
        text = "A" * 2000
        result = chunk_text(text, "parent_child", {"parent_chunk_size": 500, "child_chunk_size": 100})
        assert isinstance(result, list)
        assert len(result) > 0

    def test_overlap_alias_for_recursive(self):
        text = "A" * 300
        result = chunk_text(text, "recursive", {"chunk_size": 100, "overlap": 20})
        assert isinstance(result, list)
        assert len(result) > 1


class TestRecursive:
    """Tests for the recursive chunking strategy."""

    def test_short_text_single_chunk(self):
        result = chunk_text("Short text.", "recursive", {"chunk_size": 500})
        assert len(result) == 1
        assert result[0] == "Short text."

    def test_respects_chunk_size(self):
        text = "Word " * 200
        result = chunk_text(text, "recursive", {"chunk_size": 100, "chunk_overlap": 0})
        for chunk in result:
            assert len(chunk) <= 110  # small tolerance for separator reattachment

    def test_chunks_cover_full_text(self):
        text = "Hello world. Foo bar. Baz qux."
        result = chunk_text(text, "recursive", {"chunk_size": 500, "chunk_overlap": 0})
        combined = "".join(result)
        # All original content should be present
        assert "Hello world" in combined
        assert "Baz qux" in combined

    def test_overlap_produces_more_chunks(self):
        text = "A" * 500
        no_overlap = chunk_text(text, "recursive", {"chunk_size": 100, "chunk_overlap": 0})
        with_overlap = chunk_text(text, "recursive", {"chunk_size": 100, "chunk_overlap": 30})
        assert len(with_overlap) >= len(no_overlap)


class TestParentChild:
    """Tests for the parent-child chunking strategy."""

    def test_returns_child_chunks(self):
        text = "Section one content. " * 20 + "\n\n" + "Section two content. " * 20
        result = chunk_text(text, "parent_child", {"parent_size": 200, "child_size": 50})
        assert isinstance(result, list)
        assert len(result) > 0

    def test_child_chunks_smaller_than_parent(self):
        text = "A" * 1000
        result = chunk_text(text, "parent_child", {"parent_size": 500, "child_size": 100})
        for chunk in result:
            assert len(chunk) <= 110


class TestSemantic:
    """Tests for the semantic chunking strategy."""

    def test_splits_on_headings(self):
        # Each section must be large enough to not merge into one chunk
        text = "# Section 1\n" + "Content one. " * 50 + "\n\n# Section 2\n" + "Content two. " * 50
        result = chunk_text(text, "semantic", {"max_chunk_size": 500})
        assert len(result) >= 2

    def test_splits_on_double_newlines(self):
        # Paragraphs large enough to not merge
        text = ("Paragraph one. " * 30) + "\n\n" + ("Paragraph two. " * 30) + "\n\n" + ("Paragraph three. " * 30)
        result = chunk_text(text, "semantic", {"max_chunk_size": 300})
        assert len(result) >= 3

    def test_oversized_section_falls_back_to_recursive(self):
        text = "A" * 2000
        result = chunk_text(text, "semantic", {"max_chunk_size": 500})
        assert all(len(c) <= 510 for c in result)

    def test_merges_small_sections(self):
        text = "A\n\nB\n\nC"
        result = chunk_text(text, "semantic", {"max_chunk_size": 1000})
        # Small sections merge into one
        assert len(result) == 1


class TestFixedOverlap:
    """Tests for the fixed-overlap chunking strategy."""

    def test_basic_chunking(self):
        text = "A" * 500
        result = chunk_text(text, "fixed_overlap", {"chunk_size": 100, "overlap": 20})
        assert len(result) > 1

    def test_chunk_size_respected(self):
        text = "B" * 500
        result = chunk_text(text, "fixed_overlap", {"chunk_size": 100, "overlap": 20})
        for chunk in result:
            assert len(chunk) <= 100

    def test_overlap_content(self):
        text = "ABCDEFGHIJ" * 10  # 100 chars
        result = chunk_text(text, "fixed_overlap", {"chunk_size": 30, "overlap": 10})
        # Each chunk after the first should start with the last 10 chars of the previous
        for i in range(1, len(result)):
            prev_end = result[i - 1][-10:]
            curr_start = result[i][:10]
            assert prev_end == curr_start

    def test_chunk_size_lte_overlap_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be greater than overlap"):
            chunk_text("hello", "fixed_overlap", {"chunk_size": 50, "overlap": 50})

    def test_short_text_single_chunk(self):
        result = chunk_text("Hi", "fixed_overlap", {"chunk_size": 100, "overlap": 20})
        assert len(result) == 1
        assert result[0] == "Hi"


class TestChunkTextPipeline:
    """Tests for the 2-step pipeline."""

    def test_single_step(self):
        text = "A" * 500
        result = chunk_text_pipeline(text, "recursive", {"chunk_size": 100}, None, None)
        assert isinstance(result, list)
        assert len(result) > 1

    def test_two_step_pipeline(self):
        text = "A" * 1000
        result = chunk_text_pipeline(
            text,
            "recursive", {"chunk_size": 500, "chunk_overlap": 0},
            "fixed_overlap", {"chunk_size": 100, "overlap": 10},
        )
        assert isinstance(result, list)
        # Two-step should produce more/smaller chunks than step 1 alone
        step1_only = chunk_text_pipeline(text, "recursive", {"chunk_size": 500, "chunk_overlap": 0}, None, None)
        assert len(result) >= len(step1_only)

    def test_empty_text_pipeline(self):
        result = chunk_text_pipeline("", "recursive", {}, "fixed_overlap", {"chunk_size": 100, "overlap": 10})
        assert result == []
