"""Unit tests for log-query cleaning and hard-case mining."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.case_mining import (
    clean_log_queries,
    find_hard_cases,
    generate_variants,
    mine_hard_cases,
)

pytestmark = pytest.mark.unit


class TestCleanLogQueries:
    def test_drops_trivial_and_duplicates(self):
        kept, skipped = clean_log_queries([
            "How do I reset my password?",
            "hi",
            "  how do i reset   my password? ",  # dupe modulo case/whitespace
            "",
            "What plans do you offer?",
        ])
        assert kept == ["How do I reset my password?", "What plans do you offer?"]
        assert skipped == {"trivial": 2, "duplicate": 1}

    def test_caps_total(self):
        queries = [f"unique question number {i}?" for i in range(1500)]
        kept, _ = clean_log_queries(queries)
        assert len(kept) == 1000


def _llm_result(content: str) -> dict:
    return {"content": content, "usage": {"prompt_tokens": 5, "completion_tokens": 5}}


class TestGenerateVariants:
    async def test_parses_and_caps_variants(self):
        mock = AsyncMock(return_value=_llm_result("1. variant one\n2. variant two\n3. extra"))
        with patch("app.services.case_mining.chat_completion", mock):
            variants = await generate_variants("original?", 2, "gpt-test")
        assert variants == ["variant one", "variant two"]

    async def test_failure_returns_empty(self):
        mock = AsyncMock(side_effect=RuntimeError("rate limit"))
        with patch("app.services.case_mining.chat_completion", mock):
            assert await generate_variants("original?", 2, "gpt-test") == []


@pytest.fixture
def experiment_db(sample_project):
    """Completed experiment with three scored results (0.2 / 0.6 / 0.9)."""
    conn, pid = sample_project
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'base-set')", (pid,)
    ).lastrowid
    exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status) VALUES (?, ?, 'exp-1', 'm', 'completed')",
        (pid, ts),
    ).lastrowid

    def add_result(question: str, score: float, metadata: dict | None = None) -> int:
        qid = conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, reference_contexts, status, metadata_json) "
            "VALUES (?, ?, 'the answer', '[\"ctx\"]', 'approved', ?)",
            (ts, question, json.dumps(metadata) if metadata else None),
        ).lastrowid
        conn.execute(
            "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json) "
            "VALUES (?, ?, 'r', '[]', ?, '{}')",
            (exp, qid, json.dumps({"bleu_score": score, "note": "text-ignored"})),
        )
        conn.commit()
        return qid

    bad_qid = add_result("bad question?", 0.2, {"source_chunk_ids": [11, 12]})
    add_result("mid question?", 0.6)
    add_result("good question?", 0.9)
    return conn, pid, exp, bad_qid


class TestFindHardCases:
    def test_selects_below_threshold_sorted(self, experiment_db):
        conn, _pid, exp, _ = experiment_db
        cases = find_hard_cases(conn, exp, threshold=0.7, limit=10)
        assert [c["question"] for c in cases] == ["bad question?", "mid question?"]
        assert cases[0]["mean_score"] == 0.2

    def test_limit(self, experiment_db):
        conn, _pid, exp, _ = experiment_db
        cases = find_hard_cases(conn, exp, threshold=0.7, limit=1)
        assert [c["question"] for c in cases] == ["bad question?"]


class TestMineHardCases:
    async def test_creates_test_set_with_provenance(self, experiment_db):
        conn, pid, exp, bad_qid = experiment_db
        mock = AsyncMock(return_value=_llm_result("variant A\nvariant B"))
        with patch("app.services.case_mining.chat_completion", mock):
            result = await mine_hard_cases(
                conn, pid, exp, "exp-1",
                threshold=0.5, variants_per_question=2, max_questions=10, model="gpt-test",
            )

        assert result["hard_cases"] == 1
        assert result["variants_created"] == 2
        questions = conn.execute(
            "SELECT * FROM test_questions WHERE test_set_id = ?", (result["test_set_id"],)
        ).fetchall()
        assert len(questions) == 2
        q = questions[0]
        assert q["reference_answer"] == "the answer"
        assert q["question_type"] == "hard_case_mined"
        assert q["status"] == "approved"
        meta = json.loads(q["metadata_json"])
        assert meta["source_chunk_ids"] == [11, 12]  # provenance inherited
        assert meta["variant_of_question_id"] == bad_qid
        assert meta["hard_case"] is True

    async def test_all_failures_leaves_no_test_set(self, experiment_db):
        conn, pid, exp, _ = experiment_db
        mock = AsyncMock(side_effect=RuntimeError("down"))
        with patch("app.services.case_mining.chat_completion", mock):
            result = await mine_hard_cases(
                conn, pid, exp, "exp-1",
                threshold=0.5, variants_per_question=2, max_questions=10, model="gpt-test",
            )
        assert result["test_set_id"] is None
        assert result["failures"] == 1
        leftover = conn.execute(
            "SELECT COUNT(*) AS cnt FROM test_sets WHERE name LIKE 'Hard cases%'"
        ).fetchone()["cnt"]
        assert leftover == 0

    async def test_no_hard_cases(self, experiment_db):
        conn, pid, exp, _ = experiment_db
        result = await mine_hard_cases(
            conn, pid, exp, "exp-1",
            threshold=0.1, variants_per_question=2, max_questions=10, model="gpt-test",
        )
        assert result == {
            "test_set_id": None, "hard_cases": 0, "variants_created": 0, "failures": 0,
        }
