"""Shared fixtures for all tests."""

import sys
import types
from unittest.mock import patch


# ragas imports ChatVertexAI from langchain_community.chat_models.vertexai at module
# level, but this sub-module was removed in langchain-community 0.3+. Provide a stub
# so test collection succeeds without requiring the google-cloud-aiplatform stack.
def _ensure_vertexai_stub() -> None:
    stub_key = "langchain_community.chat_models.vertexai"
    if stub_key in sys.modules:
        return
    # Ensure the real package is imported first so we don't shadow it with a fake module.
    try:
        import langchain_community  # noqa: F401
        import langchain_community.chat_models  # noqa: F401
    except ImportError:
        pass
    if stub_key not in sys.modules:
        stub = types.ModuleType(stub_key)
        stub.ChatVertexAI = type("ChatVertexAI", (), {})  # type: ignore[attr-defined]
        sys.modules[stub_key] = stub
        parent = sys.modules.get("langchain_community.chat_models")
        if parent is not None:
            parent.vertexai = stub

_ensure_vertexai_stub()

import pytest  # noqa: E402 — must import after vertexai stub is installed


@pytest.fixture
def tmp_db(tmp_path):
    """Create a fresh in-memory-like SQLite database with the full schema."""
    db_path = tmp_path / "test.db"
    # Patch DATABASE_PATH so init_db writes to our temp location
    with patch("db.init.DATABASE_PATH", db_path):
        import db.init as db_module
        from db.init import init_db

        # Reset global connection
        db_module._connection = None
        conn = init_db()
        yield conn
        conn.close()
        db_module._connection = None


@pytest.fixture
def sample_project(tmp_db):
    """Insert a sample project and return (conn, project_id)."""
    tmp_db.execute("INSERT INTO projects (name, description) VALUES (?, ?)", ("Test Project", "A test"))
    tmp_db.commit()
    project_id = tmp_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return tmp_db, project_id


@pytest.fixture
def sample_texts():
    """Sample texts for chunking and embedding tests."""
    return [
        "The quick brown fox jumps over the lazy dog. This is a test sentence.",
        "Machine learning is a subset of artificial intelligence. It enables computers to learn from data.",
        "Python is a popular programming language. It is used for web development and data science.",
    ]


@pytest.fixture
def sample_chunks():
    """Pre-chunked text samples."""
    return [
        "The quick brown fox jumps over the lazy dog.",
        "Machine learning is a subset of artificial intelligence.",
        "Python is a popular programming language.",
        "It enables computers to learn from data.",
        "It is used for web development and data science.",
    ]


@pytest.fixture
def mock_openai_embeddings():
    """Mock OpenAI embedding responses."""
    async def _mock_create(**kwargs):
        texts = kwargs.get("input", [])
        # Return fake 3-dimensional embeddings
        class FakeData:
            def __init__(self, emb):
                self.embedding = emb
        class FakeResponse:
            def __init__(self, n):
                self.data = [FakeData([0.1 * (i + 1), 0.2 * (i + 1), 0.3 * (i + 1)]) for i in range(n)]
        return FakeResponse(len(texts))

    return _mock_create


@pytest.fixture
def mock_chat_completion():
    """Mock LLM chat completion responses."""
    async def _mock(**kwargs):
        return {
            "content": "This is a mock LLM response.",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
    return _mock
