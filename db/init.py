import sqlite3
from pathlib import Path

DATABASE_PATH = Path("data/ragas.db")

_connection: sqlite3.Connection | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunk_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    method TEXT NOT NULL,
    params_json TEXT NOT NULL,
    step2_method TEXT,
    step2_params_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_config_id INTEGER NOT NULL REFERENCES chunk_configs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    parent_chunk_id INTEGER REFERENCES chunks(id),
    embedding_blob BLOB,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS embedding_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    model_name TEXT,
    params_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    embedding_config_id INTEGER NOT NULL REFERENCES embedding_configs(id),
    chunk_config_id INTEGER NOT NULL REFERENCES chunk_configs(id),
    search_type TEXT NOT NULL,
    sparse_config_id INTEGER REFERENCES embedding_configs(id),
    alpha REAL,
    llm_model TEXT NOT NULL,
    llm_params_json TEXT,
    top_k INTEGER NOT NULL DEFAULT 5,
    system_prompt TEXT,
    response_mode TEXT NOT NULL DEFAULT 'single_shot',
    max_steps INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS test_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    generation_config_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS test_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_set_id INTEGER NOT NULL REFERENCES test_sets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_contexts TEXT,
    question_type TEXT,
    persona TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    user_edited_answer TEXT,
    user_notes TEXT,
    reviewed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    test_set_id INTEGER NOT NULL REFERENCES test_sets(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    model_params_json TEXT,
    retrieval_config_json TEXT,
    chunk_config_id INTEGER REFERENCES chunk_configs(id),
    embedding_config_id INTEGER REFERENCES embedding_configs(id),
    rag_config_id INTEGER REFERENCES rag_configs(id),
    baseline_experiment_id INTEGER REFERENCES experiments(id),
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    test_question_id INTEGER NOT NULL REFERENCES test_questions(id),
    response TEXT,
    retrieved_contexts TEXT,
    metrics_json TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    signal TEXT NOT NULL,
    suggestion TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    implemented BOOLEAN DEFAULT FALSE,
    config_field TEXT,
    suggested_value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT,
    source_type TEXT NOT NULL DEFAULT 'csv',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    endpoint_url TEXT NOT NULL,
    api_key TEXT,
    headers_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id)
);
"""


def init_db() -> sqlite3.Connection:
    global _connection

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    # Migration: add rag_config_id to experiments if column missing (stale DB)
    try:
        conn.execute("ALTER TABLE experiments ADD COLUMN rag_config_id INTEGER REFERENCES rag_configs(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add baseline_experiment_id to experiments (Phase 8 — iteration tracking)
    try:
        conn.execute("ALTER TABLE experiments ADD COLUMN baseline_experiment_id INTEGER REFERENCES experiments(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add config_field and suggested_value to suggestions (Phase 8 — structured config mapping)
    try:
        conn.execute("ALTER TABLE suggestions ADD COLUMN config_field TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE suggestions ADD COLUMN suggested_value TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add max_steps to rag_configs (Phase 4 — multi-step RAG, missed migration for stale DB)
    try:
        conn.execute("ALTER TABLE rag_configs ADD COLUMN max_steps INTEGER NOT NULL DEFAULT 3")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add reranker fields to rag_configs
    for col_sql in [
        "ALTER TABLE rag_configs ADD COLUMN reranker_model TEXT",
        "ALTER TABLE rag_configs ADD COLUMN reranker_top_k INTEGER",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Migration: add context_label to documents (for contextual embeddings)
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN context_label TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add filter_params_json to chunk_configs (post-chunking quality filters)
    try:
        conn.execute("ALTER TABLE chunk_configs ADD COLUMN filter_params_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    _connection = conn
    return conn


def get_db() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = init_db()
    return _connection
