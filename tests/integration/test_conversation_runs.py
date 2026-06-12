"""Integration tests: multi-turn conversation experiments and the CI gate."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import db.init
import main
from pipeline.bot_connectors.base import BotResponse

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def project(client):
    import uuid

    resp = client.post(
        "/api/projects", json={"name": f"conv-it-{uuid.uuid4().hex[:8]}", "description": ""}
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


class FakeConnector:
    """Echo connector that records every call's history."""

    def __init__(self):
        self.calls = []

    async def query(self, question, *, system_context=None, history=None):
        self.calls.append({"question": question, "history": list(history or [])})
        return BotResponse(answer=f"echo: {question}", citations=[], raw_response={})


def _seed_conversation_experiment(pid: int) -> dict:
    conn = db.init.get_db()
    ts = conn.execute(
        "INSERT INTO test_sets (project_id, name) VALUES (?, 'conv')", (pid,)
    ).lastrowid
    qid = conn.execute(
        """INSERT INTO test_questions
           (test_set_id, question, reference_answer, reference_contexts, question_type, persona, status, metadata_json)
           VALUES (?, 'What is my refund window?', '30 days.', '[]', 'uploaded', '', 'approved', ?)""",
        (ts, json.dumps({"turns": ["I am on the Pro plan.", "I pay annually."]})),
    ).lastrowid
    bot = conn.execute(
        "INSERT INTO bot_configs (project_id, name, connector_type, config_json, prompt_for_sources) "
        "VALUES (?, 'fake-bot', 'custom', '{}', 0)",
        (pid,),
    ).lastrowid
    exp = conn.execute(
        "INSERT INTO experiments (project_id, test_set_id, name, model, status, bot_config_id) "
        "VALUES (?, ?, 'conv-exp', 'external', 'pending', ?)",
        (pid, ts, bot),
    ).lastrowid
    conn.commit()
    return {"experiment_id": exp, "question_id": qid}


class TestConversationRun:
    def test_turns_played_with_history(self, client, project):
        seeded = _seed_conversation_experiment(project)
        fake = FakeConnector()

        with (
            patch("app.services.experiment_runner.create_connector", return_value=fake),
            patch("app.services.experiment_runner.setup_scorers", return_value=({}, {}, None)),
        ):
            r = client.post(
                f"/api/projects/{project}/experiments/{seeded['experiment_id']}/run",
                json={"metrics": [], "concurrency": 1},
            )
            assert r.status_code == 200, r.text

            # TestClient drives the loop between requests — poll until done
            prog: dict = {}
            for _ in range(300):
                prog = client.get(
                    f"/api/projects/{project}/experiments/{seeded['experiment_id']}/progress-snapshot"
                ).json()
                if prog.get("phase") in ("completed", "error", "cancelled"):
                    break
            assert prog.get("phase") == "completed", prog

        # 3 calls: two setup turns + the final question
        assert [c["question"] for c in fake.calls] == [
            "I am on the Pro plan.",
            "I pay annually.",
            "What is my refund window?",
        ]
        # Final call carries the full 4-message history
        final_history = fake.calls[-1]["history"]
        assert [m["role"] for m in final_history] == ["user", "assistant", "user", "assistant"]
        assert final_history[1]["content"] == "echo: I am on the Pro plan."

        # Transcript persisted with the result
        conn = db.init.get_db()
        row = conn.execute(
            "SELECT response, metadata_json FROM experiment_results WHERE experiment_id = ?",
            (seeded["experiment_id"],),
        ).fetchone()
        assert row["response"] == "echo: What is my refund window?"
        meta = json.loads(row["metadata_json"])
        assert len(meta["transcript"]) == 4


class TestGate:
    @staticmethod
    def _seed_completed(pid: int, faithfulness: float) -> int:
        conn = db.init.get_db()
        ts = conn.execute(
            "INSERT INTO test_sets (project_id, name) VALUES (?, 'gate')", (pid,)
        ).lastrowid
        qid = conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, reference_contexts, question_type, persona, status) "
            "VALUES (?, 'Q?', 'A', '[]', 'uploaded', '', 'approved')",
            (ts,),
        ).lastrowid
        exp = conn.execute(
            "INSERT INTO experiments (project_id, test_set_id, name, model, status) "
            "VALUES (?, ?, 'gate-exp', 'm', 'completed')",
            (pid, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO experiment_results (experiment_id, test_question_id, response, retrieved_contexts, metrics_json) "
            "VALUES (?, ?, 'r', '[]', ?)",
            (exp, qid, json.dumps({"faithfulness": faithfulness})),
        )
        conn.commit()
        return exp

    def test_gate_passes(self, client, project):
        exp = self._seed_completed(project, 0.9)
        r = client.get(
            f"/api/projects/{project}/experiments/{exp}/gate",
            params={"thresholds": "faithfulness:0.7"},
        )
        assert r.status_code == 200
        assert r.json()["pass"] is True

    def test_gate_fails_strict_412(self, client, project):
        exp = self._seed_completed(project, 0.5)
        r = client.get(
            f"/api/projects/{project}/experiments/{exp}/gate",
            params={"thresholds": "faithfulness:0.7", "strict": "true"},
        )
        assert r.status_code == 412
        assert r.json()["pass"] is False

    def test_missing_metric_fails_gate(self, client, project):
        exp = self._seed_completed(project, 0.9)
        r = client.get(
            f"/api/projects/{project}/experiments/{exp}/gate",
            params={"thresholds": "refusal_accuracy:0.5"},
        )
        assert r.json()["pass"] is False

    def test_min_overall(self, client, project):
        exp = self._seed_completed(project, 0.9)
        r = client.get(
            f"/api/projects/{project}/experiments/{exp}/gate",
            params={"min_overall": "0.8"},
        )
        assert r.json()["pass"] is True

    def test_no_criteria_400(self, client, project):
        exp = self._seed_completed(project, 0.9)
        r = client.get(f"/api/projects/{project}/experiments/{exp}/gate")
        assert r.status_code == 400


class TestTurnsUpload:
    def test_turns_column_parsing(self, client, project):
        csv_content = (
            "question,answer,turns\n"
            '"What is my refund window?","30 days.","I am on Pro.|||I pay annually."\n'
            '"Single turn question?","Answer.",""\n'
        )
        r = client.post(
            f"/api/projects/{project}/test-sets/upload",
            files={"file": ("conv.csv", csv_content, "text/csv")},
            data={
                "question_column": "question",
                "answer_column": "answer",
                "turns_column": "turns",
            },
        )
        assert r.status_code == 201, r.text
        questions = r.json().get("questions") or r.json().get("inserted") or []
        by_q = {q["question"]: q for q in questions}
        multi = by_q["What is my refund window?"]
        assert (multi["metadata"] or {})["turns"] == ["I am on Pro.", "I pay annually."]
        single = by_q["Single turn question?"]
        assert not (single.get("metadata") or {}).get("turns")
