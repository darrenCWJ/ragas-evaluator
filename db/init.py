"""Database initialisation and connection helpers.

Supports two backends selected at startup:
- **PostgreSQL** (Neon or any Postgres): set ``DATABASE_URL`` env var.
- **SQLite** (default, local dev): no env var required.

A thin ``_PgConnection`` / ``_PgCursor`` wrapper makes the PostgreSQL
connection behave like ``sqlite3`` so every route module works unchanged.
"""

import sqlite3
from typing import Any

from config import DATABASE_PATH, DATABASE_URL

# ---------------------------------------------------------------------------
# Detect backend
# ---------------------------------------------------------------------------

_USE_PG = bool(DATABASE_URL)

if _USE_PG:
    import psycopg2
    import psycopg2.extras

# ---------------------------------------------------------------------------
# PostgreSQL compatibility shim
# ---------------------------------------------------------------------------

class _PgCursor:
    """Wraps a psycopg2 DictCursor to look like sqlite3.Cursor."""

    def __init__(self, cursor: Any) -> None:
        self._cur = cursor
        self.lastrowid: int | None = None

    def fetchall(self) -> list:
        return self._cur.fetchall()

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchmany(self, size: int) -> list:
        return self._cur.fetchmany(size)

    @property
    def description(self) -> Any:
        return self._cur.description

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class _PgConnection:
    """Wraps a psycopg2 connection to look like sqlite3.Connection."""

    def __init__(self, pg_conn: Any) -> None:
        self._conn = pg_conn

    def execute(self, sql: str, params: tuple = ()) -> _PgCursor:
        # Replace SQLite ? placeholders with psycopg2 %s
        pg_sql = sql.replace("?", "%s")

        # Append RETURNING id to INSERTs so lastrowid works
        stripped = pg_sql.strip().upper()
        is_insert = stripped.startswith("INSERT") and "RETURNING" not in stripped
        if is_insert:
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"

        cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(pg_sql, params or None)

        wrapper = _PgCursor(cur)
        if is_insert:
            row = cur.fetchone()
            wrapper.lastrowid = row["id"] if row else None
        return wrapper

    def executescript(self, sql: str) -> None:
        """Execute multiple semicolon-separated statements using savepoints."""
        cur = self._conn.cursor()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                cur.execute("SAVEPOINT _sp")
                cur.execute(stmt)
                cur.execute("RELEASE SAVEPOINT _sp")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT _sp")
        self._conn.commit()

    def executemany(self, sql: str, seq_of_params) -> None:
        pg_sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        for params in seq_of_params:
            cur.execute(pg_sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # No-op to allow ``conn.row_factory = sqlite3.Row`` assignments
    @property
    def row_factory(self) -> None:
        return None

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Schema SQL — SQLite
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    judge_model_assignments_json TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content TEXT NOT NULL,
    context_label TEXT,
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
    filter_params_json TEXT,
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
    reranker_model TEXT,
    reranker_top_k INTEGER,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS test_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    generation_config_json TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS test_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_set_id INTEGER NOT NULL REFERENCES test_sets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_contexts TEXT,
    question_type TEXT,
    category TEXT,
    persona TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    user_edited_answer TEXT,
    user_edited_contexts TEXT,
    user_notes TEXT,
    metadata_json TEXT,
    reviewed_at TIMESTAMP
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
    bot_config_id INTEGER REFERENCES bot_configs(id),
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
    reference_answer TEXT,
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
    refined_prompt TEXT,
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
    kg_source TEXT NOT NULL DEFAULT 'chunks',
    num_nodes INTEGER NOT NULL DEFAULT 0,
    num_chunks INTEGER NOT NULL DEFAULT 0,
    is_complete BOOLEAN NOT NULL DEFAULT TRUE,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER NOT NULL DEFAULT 4,
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    UNIQUE(project_id, chunks_hash)
);

CREATE TABLE IF NOT EXISTS multi_llm_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_result_id INTEGER NOT NULL REFERENCES experiment_results(id) ON DELETE CASCADE,
    evaluator_index INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    score REAL NOT NULL,
    claims_json TEXT NOT NULL,
    custom_metric_name TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS evaluator_claim_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id INTEGER NOT NULL REFERENCES multi_llm_evaluations(id) ON DELETE CASCADE,
    claim_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    comment TEXT,
    annotated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    UNIQUE(evaluation_id, claim_index)
);
"""

# ---------------------------------------------------------------------------
# Schema SQL — PostgreSQL (Neon)
# ---------------------------------------------------------------------------

PG_SCHEMA_SQL = SCHEMA_SQL \
    .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY") \
    .replace("BLOB", "BYTEA") \
    .replace("DEFAULT (datetime('now', 'localtime'))", "DEFAULT NOW()")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# SQL fragment for current timestamp — use in f-strings or string concatenation
NOW_SQL = "NOW()" if _USE_PG else "datetime('now', 'localtime')"


def json_extract_sql(column: str, key: str) -> str:
    """Return SQL to extract a scalar value from a JSON text column.

    SQLite:    json_extract(column, '$.key')
    PostgreSQL: (column::jsonb->>'key')
    """
    if _USE_PG:
        return f"({column}::jsonb->>'{key}')"
    return f"json_extract({column}, '$.{key}')"

_connection: sqlite3.Connection | _PgConnection | None = None


def is_integrity_error(exc: Exception) -> bool:
    """Return True if *exc* is a unique/FK constraint violation on either backend."""
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    if _USE_PG:
        return isinstance(exc, psycopg2.IntegrityError)
    return False


def _add_column_if_missing(
    conn: sqlite3.Connection | _PgConnection,
    alter_sql: str,
) -> None:
    """Add a column to a table, ignoring errors if it already exists."""
    if _USE_PG:
        pg_sql = alter_sql.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
        conn.execute(pg_sql)
        conn.commit()
    else:
        try:
            conn.execute(alter_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists


def _make_pg_connection() -> _PgConnection:
    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_conn.autocommit = False
    return _PgConnection(pg_conn)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection | _PgConnection:
    global _connection

    if _USE_PG:
        conn = _make_pg_connection()
        conn.executescript(PG_SCHEMA_SQL)
    else:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA foreign_keys = ON")
        raw.executescript(SCHEMA_SQL)
        raw.commit()
        conn = raw

    # Migrations — safe to re-run; columns are added only when missing
    _add_column_if_missing(conn, "ALTER TABLE experiments ADD COLUMN rag_config_id INTEGER REFERENCES rag_configs(id)")
    _add_column_if_missing(conn, "ALTER TABLE experiments ADD COLUMN baseline_experiment_id INTEGER REFERENCES experiments(id)")
    _add_column_if_missing(conn, "ALTER TABLE suggestions ADD COLUMN config_field TEXT")
    _add_column_if_missing(conn, "ALTER TABLE suggestions ADD COLUMN suggested_value TEXT")
    _add_column_if_missing(conn, "ALTER TABLE rag_configs ADD COLUMN max_steps INTEGER NOT NULL DEFAULT 3")
    _add_column_if_missing(conn, "ALTER TABLE rag_configs ADD COLUMN reranker_model TEXT")
    _add_column_if_missing(conn, "ALTER TABLE rag_configs ADD COLUMN reranker_top_k INTEGER")
    _add_column_if_missing(conn, "ALTER TABLE documents ADD COLUMN context_label TEXT")
    _add_column_if_missing(conn, "ALTER TABLE chunk_configs ADD COLUMN filter_params_json TEXT")
    _add_column_if_missing(conn, "ALTER TABLE experiments ADD COLUMN bot_config_id INTEGER REFERENCES bot_configs(id)")
    _add_column_if_missing(conn, "ALTER TABLE test_questions ADD COLUMN category TEXT")
    _add_column_if_missing(conn, "ALTER TABLE test_sets ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
    _add_column_if_missing(conn, "ALTER TABLE test_sets ADD COLUMN error_message TEXT")
    _add_column_if_missing(conn, "ALTER TABLE knowledge_graphs ADD COLUMN last_heartbeat TIMESTAMP")
    _add_column_if_missing(conn, "ALTER TABLE knowledge_graphs ADD COLUMN chunk_config_id INTEGER REFERENCES chunk_configs(id)")
    _add_column_if_missing(conn, "ALTER TABLE knowledge_graphs ADD COLUMN kg_source TEXT NOT NULL DEFAULT 'chunks'")
    _add_column_if_missing(conn, "ALTER TABLE test_questions ADD COLUMN user_edited_contexts TEXT")
    _add_column_if_missing(conn, "ALTER TABLE test_questions ADD COLUMN metadata_json TEXT")
    _add_column_if_missing(conn, "ALTER TABLE external_baselines ADD COLUMN bot_config_id INTEGER REFERENCES bot_configs(id) ON DELETE CASCADE")
    _add_column_if_missing(conn, "ALTER TABLE external_baselines ADD COLUMN reference_answer TEXT")
    _add_column_if_missing(conn, "ALTER TABLE custom_metrics ADD COLUMN refined_prompt TEXT")
    _add_column_if_missing(conn, "ALTER TABLE multi_llm_evaluations ADD COLUMN custom_metric_name TEXT")
    _add_column_if_missing(conn, "ALTER TABLE projects ADD COLUMN judge_model_assignments_json TEXT")

    # Backfill NULL chunk_config_id on knowledge_graphs (SQLite only — PG starts fresh)
    if not _USE_PG:
        import hashlib
        orphan_kgs = conn.execute(
            "SELECT id, project_id, chunks_hash FROM knowledge_graphs WHERE chunk_config_id IS NULL"
        ).fetchall()
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


def get_db() -> sqlite3.Connection | _PgConnection:
    global _connection
    if _connection is None:
        _connection = init_db()
        return _connection

    if _USE_PG:
        # Neon serverless closes idle connections — reconnect transparently
        try:
            if _connection._conn.closed:
                raise Exception("closed")
            _connection._conn.cursor().execute("SELECT 1")
        except Exception:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = _make_pg_connection()

    return _connection


def get_thread_db() -> sqlite3.Connection | _PgConnection:
    """Return a fresh DB connection for background threads.

    The caller is responsible for closing it when done.
    """
    if _USE_PG:
        return _make_pg_connection()

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
