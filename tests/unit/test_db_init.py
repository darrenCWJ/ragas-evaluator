"""Unit tests for db/init.py."""

import sqlite3
from unittest.mock import patch

import pytest


class TestInitDb:
    def test_creates_all_tables(self, tmp_db):
        tables = [
            row[0]
            for row in tmp_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        expected = [
            "api_configs",
            "chunk_configs",
            "chunks",
            "documents",
            "embedding_configs",
            "experiment_results",
            "experiments",
            "external_baselines",
            "projects",
            "rag_configs",
            "suggestions",
            "test_questions",
            "test_sets",
        ]
        for table in expected:
            assert table in tables, f"Missing table: {table}"

    def test_row_factory_is_set(self, tmp_db):
        assert tmp_db.row_factory == sqlite3.Row

    def test_foreign_keys_enabled(self, tmp_db):
        result = tmp_db.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1

    def test_wal_mode(self, tmp_db):
        result = tmp_db.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"

    def test_idempotent_init(self, tmp_path):
        """Calling init_db twice should not fail."""
        import db.init as db_module

        db_path = tmp_path / "test2.db"
        with patch("db.init.DATABASE_PATH", db_path):
            db_module._connection = None
            conn1 = db_module.init_db()
            db_module._connection = None
            conn2 = db_module.init_db()
            conn1.close()
            conn2.close()
            db_module._connection = None


class TestGetDb:
    def test_returns_connection(self, tmp_path):
        import db.init as db_module

        db_path = tmp_path / "test3.db"
        with patch("db.init.DATABASE_PATH", db_path):
            db_module._connection = None
            conn = db_module.get_db()
            assert conn is not None
            assert conn.row_factory == sqlite3.Row
            conn.close()
            db_module._connection = None

    def test_reuses_connection(self, tmp_path):
        import db.init as db_module

        db_path = tmp_path / "test4.db"
        with patch("db.init.DATABASE_PATH", db_path):
            db_module._connection = None
            conn1 = db_module.get_db()
            conn2 = db_module.get_db()
            assert conn1 is conn2
            conn1.close()
            db_module._connection = None


class TestSchema:
    def test_projects_unique_name(self, tmp_db):
        tmp_db.execute("INSERT INTO projects (name) VALUES ('p1')")
        tmp_db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.execute("INSERT INTO projects (name) VALUES ('p1')")
            tmp_db.commit()

    def test_cascade_delete_project(self, tmp_db):
        tmp_db.execute("INSERT INTO projects (name) VALUES ('p1')")
        tmp_db.commit()
        pid = tmp_db.execute("SELECT id FROM projects WHERE name='p1'").fetchone()[0]

        tmp_db.execute(
            "INSERT INTO documents (project_id, filename, file_type, content) VALUES (?, 'f.txt', 'txt', 'c')",
            (pid,),
        )
        tmp_db.commit()

        tmp_db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        tmp_db.commit()

        docs = tmp_db.execute("SELECT * FROM documents WHERE project_id = ?", (pid,)).fetchall()
        assert len(docs) == 0

    def test_experiments_columns_exist(self, tmp_db):
        """Verify migration columns are present."""
        info = tmp_db.execute("PRAGMA table_info(experiments)").fetchall()
        col_names = [row[1] for row in info]
        assert "rag_config_id" in col_names
        assert "baseline_experiment_id" in col_names

    def test_suggestions_columns_exist(self, tmp_db):
        info = tmp_db.execute("PRAGMA table_info(suggestions)").fetchall()
        col_names = [row[1] for row in info]
        assert "config_field" in col_names
        assert "suggested_value" in col_names

    def test_rag_configs_max_steps(self, tmp_db):
        info = tmp_db.execute("PRAGMA table_info(rag_configs)").fetchall()
        col_names = [row[1] for row in info]
        assert "max_steps" in col_names
