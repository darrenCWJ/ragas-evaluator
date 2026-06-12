"""Unit tests for small-to-big retrieval: parent_child_pairs + _expand_to_parents."""

import json

import pytest

from pipeline.chunking import chunk_text, parent_child_pairs
from pipeline.rag import _expand_to_parents

pytestmark = pytest.mark.unit

_TEXT = (
    "Alpha section one. " * 30
    + "\n\n"
    + "Beta section two. " * 30
    + "\n\n"
    + "Gamma section three. " * 30
)


class TestParentChildPairs:
    def test_returns_parent_with_children(self):
        pairs = parent_child_pairs(_TEXT, {"parent_size": 300, "child_size": 80})
        assert len(pairs) > 1
        for parent, children in pairs:
            assert len(parent) <= 300
            assert children, "every parent must have at least one child"
            for child in children:
                assert child in parent

    def test_accepts_frontend_param_aliases_and_strings(self):
        pairs = parent_child_pairs(
            _TEXT, {"parent_chunk_size": "300", "child_chunk_size": "80"}
        )
        assert pairs
        assert all(len(p) <= 300 for p, _ in pairs)

    def test_empty_text(self):
        assert parent_child_pairs("", {}) == []
        assert parent_child_pairs("   \n ", {}) == []

    def test_flat_chunk_text_matches_pairs_children(self):
        flat = chunk_text(_TEXT, "parent_child", {"parent_size": 300, "child_size": 80})
        from_pairs = [
            child
            for _, children in parent_child_pairs(_TEXT, {"parent_size": 300, "child_size": 80})
            for child in children
        ]
        assert flat == from_pairs


def _insert_chunk(conn, doc_id: int, config_id: int, content: str, metadata: dict | None):
    cur = conn.execute(
        "INSERT INTO chunks (document_id, chunk_config_id, content, metadata_json)"
        " VALUES (?, ?, ?, ?)",
        (doc_id, config_id, content, json.dumps(metadata) if metadata else None),
    )
    return cur.lastrowid


@pytest.fixture
def parent_child_db(sample_project):
    """Project with one doc and a parent_child chunk set (2 parents, 4 children)."""
    conn, project_id = sample_project
    conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content) VALUES (?, ?, ?, ?)",
        (project_id, "doc.txt", "txt", "full text"),
    )
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json) VALUES (?, ?, ?, ?)",
        (project_id, "pc", "parent_child", "{}"),
    )
    config_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    parent_a = {"parent_key": f"{doc_id}:0", "parent_content": "PARENT A FULL WINDOW"}
    parent_b = {"parent_key": f"{doc_id}:1", "parent_content": "PARENT B FULL WINDOW"}
    ids = {
        "a1": _insert_chunk(conn, doc_id, config_id, "child a1", parent_a),
        "a2": _insert_chunk(conn, doc_id, config_id, "child a2", parent_a),
        "b1": _insert_chunk(conn, doc_id, config_id, "child b1", parent_b),
        "plain": _insert_chunk(conn, doc_id, config_id, "no-parent chunk", None),
    }
    conn.commit()
    return conn, ids


class TestExpandToParents:
    def test_swaps_child_content_for_parent(self, parent_child_db):
        conn, ids = parent_child_db
        contexts = [{"content": "child a1", "score": 0.9, "chunk_id": ids["a1"]}]

        out = _expand_to_parents(contexts, conn)

        assert out[0]["content"] == "PARENT A FULL WINDOW"
        assert out[0]["parent_key"].endswith(":0")
        # Child id is preserved for provenance/diagnostics.
        assert out[0]["chunk_id"] == ids["a1"]
        assert out[0]["score"] == 0.9

    def test_dedupes_siblings_keeping_first(self, parent_child_db):
        conn, ids = parent_child_db
        contexts = [
            {"content": "child a1", "score": 0.9, "chunk_id": ids["a1"]},
            {"content": "child a2", "score": 0.5, "chunk_id": ids["a2"]},
            {"content": "child b1", "score": 0.4, "chunk_id": ids["b1"]},
        ]

        out = _expand_to_parents(contexts, conn)

        assert [c["content"] for c in out] == ["PARENT A FULL WINDOW", "PARENT B FULL WINDOW"]
        assert out[0]["score"] == 0.9  # the best-scored sibling won

    def test_passthrough_for_chunks_without_parent_metadata(self, parent_child_db):
        conn, ids = parent_child_db
        contexts = [
            {"content": "no-parent chunk", "score": 0.8, "chunk_id": ids["plain"]},
            {"content": "child b1", "score": 0.7, "chunk_id": ids["b1"]},
        ]

        out = _expand_to_parents(contexts, conn)

        assert out[0]["content"] == "no-parent chunk"
        assert out[1]["content"] == "PARENT B FULL WINDOW"

    def test_noop_without_chunk_ids(self, parent_child_db):
        conn, _ = parent_child_db
        contexts = [{"content": "bot context", "score": None}]
        assert _expand_to_parents(contexts, conn) == contexts

    def test_noop_for_plain_chunk_sets(self, parent_child_db):
        conn, ids = parent_child_db
        contexts = [{"content": "no-parent chunk", "score": 0.8, "chunk_id": ids["plain"]}]
        assert _expand_to_parents(contexts, conn) == contexts

    def test_cross_step_dedupe_via_shared_seen_set(self, parent_child_db):
        conn, ids = parent_child_db
        seen: set[str] = set()

        step1 = _expand_to_parents(
            [{"content": "child a1", "score": 0.9, "chunk_id": ids["a1"]}], conn, seen
        )
        step2 = _expand_to_parents(
            [{"content": "child a2", "score": 0.8, "chunk_id": ids["a2"]}], conn, seen
        )

        assert len(step1) == 1
        assert step2 == []  # parent A already used in step 1

    def test_tolerates_malformed_metadata(self, parent_child_db):
        conn, ids = parent_child_db
        bad_id = _insert_chunk(conn, 1, 1, "weird", None)
        conn.execute(
            "UPDATE chunks SET metadata_json = ? WHERE id = ?", ("{not json", bad_id)
        )
        conn.commit()
        contexts = [{"content": "weird", "score": 0.5, "chunk_id": bad_id}]
        assert _expand_to_parents(contexts, conn) == contexts
