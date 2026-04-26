"""Dual-backend integration tests for db/init.py.

Validates that the SQLite and PostgreSQL compatibility shims work correctly
so bugs don't surface only in production (Priority 1).

Test groups:
- TestSQLHelpers     — unit tests for NOW_SQL, json_extract_sql, is_integrity_error
- TestSQLiteBackend  — CRUD tests exercising the real SQLite path via tmp_db
- TestPgConnectionShim — shim behaviour via a MagicMock psycopg2 connection
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# TestSQLHelpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSQLHelpers:
    """Test pure SQL-helper functions that require no real DB connection."""

    def test_now_sql_is_string(self):
        """NOW_SQL must be a non-empty string regardless of backend."""
        from db.init import NOW_SQL

        assert isinstance(NOW_SQL, str)
        assert len(NOW_SQL) > 0

    def test_json_extract_sql_returns_string_with_column_and_key(self):
        """json_extract_sql must embed the column name and key in its output."""
        from db.init import json_extract_sql

        result = json_extract_sql("metadata_json", "source")

        assert isinstance(result, str)
        assert "metadata_json" in result
        assert "source" in result

    def test_is_integrity_error_true_for_sqlite_integrity_error(self):
        """is_integrity_error returns True for sqlite3.IntegrityError."""
        from db.init import is_integrity_error

        exc = sqlite3.IntegrityError("UNIQUE constraint failed: projects.name")
        assert is_integrity_error(exc) is True

    def test_is_integrity_error_false_for_value_error(self):
        """is_integrity_error returns False for unrelated exception types."""
        from db.init import is_integrity_error

        exc = ValueError("not an integrity error")
        assert is_integrity_error(exc) is False

    def test_is_integrity_error_false_for_none(self):
        """is_integrity_error returns False when passed a plain Exception."""
        from db.init import is_integrity_error

        exc = Exception("generic error")
        assert is_integrity_error(exc) is False


# ---------------------------------------------------------------------------
# TestSQLiteBackend
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSQLiteBackend:
    """CRUD tests against a real temporary SQLite database."""

    def test_create_project(self, tmp_db):
        """INSERT into projects should succeed and be queryable."""
        tmp_db.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            ("My Project", "Integration test project"),
        )
        tmp_db.commit()

        row = tmp_db.execute(
            "SELECT name, description FROM projects WHERE name = ?",
            ("My Project",),
        ).fetchone()

        assert row is not None
        assert row["name"] == "My Project"
        assert row["description"] == "Integration test project"

    def test_fetch_nonexistent_results_returns_empty(self, tmp_db):
        """Querying experiment_results for a nonexistent experiment returns []."""
        rows = tmp_db.execute(
            "SELECT * FROM experiment_results WHERE experiment_id = ?",
            (99999,),
        ).fetchall()

        assert rows == []

    def test_project_has_auto_id(self, tmp_db):
        """Inserted projects must receive a positive auto-assigned integer id."""
        tmp_db.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            ("AutoID Project", "Check auto-increment"),
        )
        tmp_db.commit()

        row = tmp_db.execute(
            "SELECT id FROM projects WHERE name = ?",
            ("AutoID Project",),
        ).fetchone()

        assert row is not None
        assert isinstance(row["id"], int)
        assert row["id"] > 0


# ---------------------------------------------------------------------------
# TestPgConnectionShim
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPgConnectionShim:
    """Verify _PgConnection shim behaviour using a MagicMock psycopg2 connection.

    No real PostgreSQL instance is required — the tests validate SQL rewriting
    and cursor delegation logic only.
    """

    @staticmethod
    def _build_mocks():
        """Return (mock_pg_conn, mock_cursor, mock_psycopg2) with no side effects."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 42}
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = None
        mock_cursor.rowcount = 1

        mock_pg_conn = MagicMock()
        mock_pg_conn.cursor.return_value = mock_cursor

        mock_psycopg2 = MagicMock()
        mock_psycopg2.extras = MagicMock()
        mock_psycopg2.extras.DictCursor = MagicMock()

        return mock_pg_conn, mock_cursor, mock_psycopg2

    def test_placeholder_substitution_replaces_question_marks_with_percent_s(self):
        """_PgConnection.execute must replace every ? placeholder with %s."""
        import db.init as db_module
        _PgConnection = db_module._PgConnection

        mock_pg_conn, mock_cursor, mock_psycopg2 = self._build_mocks()

        with patch.object(db_module, "psycopg2", mock_psycopg2, create=True):
            shim = _PgConnection(mock_pg_conn)
            # SELECT so no RETURNING is appended — isolates placeholder logic
            shim.execute("SELECT * FROM projects WHERE id = ? AND name = ?", (1, "x"))

        call_args = mock_cursor.execute.call_args
        actual_sql = call_args[0][0]

        assert "?" not in actual_sql
        assert actual_sql.count("%s") == 2

    def test_insert_appends_returning_id(self):
        """_PgConnection.execute must append RETURNING id to INSERT statements."""
        import db.init as db_module
        _PgConnection = db_module._PgConnection

        mock_pg_conn, mock_cursor, mock_psycopg2 = self._build_mocks()

        with patch.object(db_module, "psycopg2", mock_psycopg2, create=True):
            shim = _PgConnection(mock_pg_conn)
            shim.execute(
                "INSERT INTO projects (name) VALUES (?)",
                ("TestProject",),
            )

        call_args = mock_cursor.execute.call_args
        actual_sql = call_args[0][0]

        assert "RETURNING" in actual_sql.upper()
        assert "ID" in actual_sql.upper()

    def test_select_does_not_append_returning(self):
        """_PgConnection.execute must NOT append RETURNING id to SELECT statements."""
        import db.init as db_module
        _PgConnection = db_module._PgConnection

        mock_pg_conn, mock_cursor, mock_psycopg2 = self._build_mocks()

        with patch.object(db_module, "psycopg2", mock_psycopg2, create=True):
            shim = _PgConnection(mock_pg_conn)
            shim.execute("SELECT id FROM projects WHERE id = ?", (1,))

        call_args = mock_cursor.execute.call_args
        actual_sql = call_args[0][0]

        assert "RETURNING" not in actual_sql.upper()
