import sqlite3

from config import DATABASE_PATH

_connection: sqlite3.Connection | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chunk_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    method TEXT NOT NULL,
    params_json TEXT NOT NULL,
    step2_method TEXT,
    step2_params_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_config_id INTEGER NOT NULL REFERENCES chunk_configs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    parent_chunk_id INTEGER REFERENCES chunks(id),
    embedding_blob BLOB,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS embedding_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    model_name TEXT,
    params_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
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
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS test_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    generation_config_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
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
    user_edited_contexts TEXT,
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
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    test_question_id INTEGER NOT NULL REFERENCES test_questions(id),
    response TEXT,
    retrieved_contexts TEXT,
    metrics_json TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
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
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS external_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    bot_config_id INTEGER REFERENCES bot_configs(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT,
    source_type TEXT NOT NULL DEFAULT 'csv',
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS api_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    endpoint_url TEXT NOT NULL,
    api_key TEXT,
    headers_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    UNIQUE(project_id)
);

CREATE TABLE IF NOT EXISTS bot_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_for_sources BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS source_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_result_id INTEGER NOT NULL REFERENCES experiment_results(id) ON DELETE CASCADE,
    citation_index INTEGER NOT NULL,
    title TEXT,
    url TEXT,
    status TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS human_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_result_id INTEGER NOT NULL REFERENCES experiment_results(id) ON DELETE CASCADE,
    rating TEXT NOT NULL,
    notes TEXT,
    annotated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role_description TEXT NOT NULL,
    question_style TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS custom_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    prompt TEXT,
    rubrics_json TEXT,
    min_score INTEGER NOT NULL DEFAULT 1,
    max_score INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS knowledge_graphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chunks_hash TEXT NOT NULL,
    chunk_config_id INTEGER REFERENCES chunk_configs(id),
    kg_json TEXT NOT NULL,
    num_nodes INTEGER NOT NULL DEFAULT 0,
    num_chunks INTEGER NOT NULL DEFAULT 0,
    is_complete BOOLEAN NOT NULL DEFAULT TRUE,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER NOT NULL DEFAULT 4,
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    UNIQUE(project_id, chunks_hash)
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

    # Migration: add bot_config_id to experiments (Phase 2 — external bot testing)
    try:
        conn.execute("ALTER TABLE experiments ADD COLUMN bot_config_id INTEGER REFERENCES bot_configs(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add category to test_questions (question category tagging)
    try:
        conn.execute("ALTER TABLE test_questions ADD COLUMN category TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add status and error_message to test_sets (async generation)
    try:
        conn.execute("ALTER TABLE test_sets ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE test_sets ADD COLUMN error_message TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add last_heartbeat to knowledge_graphs (stale build detection)
    try:
        conn.execute("ALTER TABLE knowledge_graphs ADD COLUMN last_heartbeat TIMESTAMP")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add chunk_config_id to knowledge_graphs (resume from KG explorer)
    try:
        conn.execute("ALTER TABLE knowledge_graphs ADD COLUMN chunk_config_id INTEGER REFERENCES chunk_configs(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add user_edited_contexts to test_questions
    try:
        conn.execute("ALTER TABLE test_questions ADD COLUMN user_edited_contexts TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add metadata_json to test_questions (domain-specific metric data)
    try:
        conn.execute("ALTER TABLE test_questions ADD COLUMN metadata_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add bot_config_id to external_baselines (CSV-as-connector)
    try:
        conn.execute("ALTER TABLE external_baselines ADD COLUMN bot_config_id INTEGER REFERENCES bot_configs(id) ON DELETE CASCADE")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: backfill NULL chunk_config_id by matching chunks_hash
    orphan_kgs = conn.execute(
        "SELECT id, project_id, chunks_hash FROM knowledge_graphs WHERE chunk_config_id IS NULL"
    ).fetchall()
    if orphan_kgs:
        import hashlib

        for kg_row in orphan_kgs:
            cc_rows = conn.execute(
                "SELECT id FROM chunk_configs WHERE project_id = ?",
                (kg_row["project_id"],),
            ).fetchall()
            for cc in cc_rows:
                chunks = conn.execute(
                    "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY rowid",
                    (cc["id"],),
                ).fetchall()
                h = hashlib.sha256()
                for c in chunks:
                    h.update(c["content"].encode("utf-8"))
                if h.hexdigest()[:16] == kg_row["chunks_hash"]:
                    conn.execute(
                        "UPDATE knowledge_graphs SET chunk_config_id = ? WHERE id = ?",
                        (cc["id"], kg_row["id"]),
                    )
                    break
        conn.commit()

    _connection = conn
    return conn


def get_db() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = init_db()
    return _connection


def get_thread_db() -> sqlite3.Connection:
    """Create a new DB connection for use in background threads.

    Unlike get_db(), this returns a fresh connection each call.
    The caller is responsible for closing it when done.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
