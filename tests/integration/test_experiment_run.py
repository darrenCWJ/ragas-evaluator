"""Integration test: run experiments end-to-end (CSV + RAG pipeline).

Hits a real OpenAI API — marked @pytest.mark.slow.  Run with:

    pytest tests/integration/test_experiment_run.py -v -s
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
import requests

logger = logging.getLogger(__name__)

MAX_WAIT = 300  # 5 minutes
POLL_INTERVAL = 5

# Representative metrics covering every scoring code path
_TEST_METRICS = [
    "faithfulness",              # q_a_ctx
    "answer_relevancy",          # q_a
    "factual_correctness",       # a_ref (LLM+embed)
    "semantic_similarity",       # a_ref (embed-only)
    "bleu_score",                # a_ref (no-deps)
    "rouge_score",               # a_ref (no-deps)
    "exact_match",               # a_ref (no-deps)
    "non_llm_string_similarity", # a_ref (no-deps)
    "string_presence",           # a_ref (no-deps)
    "context_precision",         # q_a_ref_ctx
    "context_relevance",         # q_ctx
    "summarization_score",       # a_ctx
    "context_entities_recall",   # ref_ctx
    "answer_accuracy",           # q_a_ref
    "instance_rubrics",          # q_a_rubrics_ctx
]

_DETERMINISTIC = ["bleu_score", "rouge_score", "exact_match", "non_llm_string_similarity", "string_presence"]

_RAG_METRICS = ["faithfulness", "answer_relevancy", "bleu_score", "exact_match"]

_DOC_TEXT = (
    "Retrieval-Augmented Generation (RAG) is a technique that combines "
    "information retrieval with text generation. It first retrieves relevant "
    "documents from a knowledge base, then uses them as context to generate "
    "accurate, grounded responses. RAG reduces hallucination by anchoring "
    "the model's output in real source material."
)


def _start_server(tmp_dir, port):
    """Start a uvicorn server and return (proc, db_path, base_url)."""
    db_path = str(tmp_dir / "test.db")
    env = {
        **os.environ,
        "DATABASE_PATH": db_path,
        "CHROMADB_PATH": str(tmp_dir / "chromadb"),
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base_url}/api/health", timeout=2).ok:
                return proc, db_path, base_url
        except requests.ConnectionError:
            logger.debug("test cleanup error ignored", exc_info=True)
        time.sleep(0.5)
    out = proc.stdout.read().decode() if proc.stdout else ""
    proc.kill()
    raise AssertionError(f"Server on port {port} did not start.\n{out}")


def _stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _fire_and_poll(base_url, db_path, project_id, experiment_id, metrics):
    """Fire experiment run, then poll DB until done.

    The SSE connection is kept alive in a daemon thread — the server's single
    worker needs this connection to drive the asyncio event loop for scoring.
    After DB polling confirms completion, we stop the thread cleanly.
    """
    shared = {"resp": None}

    def _sse_consumer():
        try:
            shared["resp"] = requests.post(
                f"{base_url}/api/projects/{project_id}/experiments/{experiment_id}/run",
                json={"metrics": metrics, "concurrency": 1},
                stream=True, timeout=(10, MAX_WAIT),
            )
            for line in shared["resp"].iter_lines(decode_unicode=True):
                if not line:
                    continue
                if "event: completed" in line or "event: error" in line:
                    break
        except Exception:
            logger.debug("test cleanup error ignored", exc_info=True)
        finally:
            if shared["resp"]:
                shared["resp"].close()

    t = threading.Thread(target=_sse_consumer, daemon=True)
    t.start()

    # Poll DB
    deadline = time.monotonic() + MAX_WAIT
    last_st, last_cnt = None, -1
    while time.monotonic() < deadline:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT status FROM experiments WHERE id=?", (experiment_id,)).fetchone()
            cnt = conn.execute("SELECT COUNT(*) as c FROM experiment_results WHERE experiment_id=?", (experiment_id,)).fetchone()["c"]
            conn.close()
            if row:
                st = row["status"]
                if st != last_st or cnt != last_cnt:
                    print(f"  status={st}, results={cnt}")
                    last_st, last_cnt = st, cnt
                if st == "completed":
                    if shared["resp"]:
                        shared["resp"].close()
                    t.join(timeout=5)
                    return
                if st == "failed":
                    if shared["resp"]:
                        shared["resp"].close()
                    t.join(timeout=5)
                    pytest.fail("Experiment failed")
        except sqlite3.OperationalError:
            logger.debug("test cleanup error ignored", exc_info=True)
        time.sleep(POLL_INTERVAL)

    if shared["resp"]:
        shared["resp"].close()
    t.join(timeout=5)
    pytest.fail(f"Timeout. status={last_st}, results={last_cnt}")


# ====================== CSV EXPERIMENT TESTS ======================

@pytest.fixture(scope="class")
def csv_server(tmp_path_factory):
    proc, db_path, base_url = _start_server(tmp_path_factory.mktemp("csv_test"), 18801)
    yield proc, db_path, base_url
    _stop_server(proc)


@pytest.mark.slow
@pytest.mark.integration
class TestCSVExperiment:

    def test_run_representative_metrics(self, csv_server):
        """CSV experiment with representative metrics covering all scoring paths."""
        proc, db_path, base_url = csv_server

        csv = b'question,answer,sources\nWhat is RAG?,RAG combines retrieval with generation to produce grounded answers.,"RAG Overview, Chapter 1"'

        pid = requests.post(f"{base_url}/api/projects", json={"name": "CSV Test"}).json()["id"]
        bcid = requests.post(
            f"{base_url}/api/projects/{pid}/baselines/upload-csv",
            files={"file": ("t.csv", csv, "text/csv")},
            data={"question_col": "question", "answer_col": "answer", "context_col": "sources"},
        ).json()["bot_config_id"]
        eid = requests.post(
            f"{base_url}/api/projects/{pid}/experiments",
            json={"name": "csv-test", "bot_config_id": bcid},
        ).json()["id"]

        print(f"\nCSV experiment {eid}: {len(_TEST_METRICS)} metrics, 1 question")
        _fire_and_poll(base_url, db_path, pid, eid, _TEST_METRICS)

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM experiment_results WHERE experiment_id=?", (eid,)).fetchall()
        conn.close()

        assert len(rows) == 1
        scores = json.loads(rows[0]["metrics_json"])

        for m in _TEST_METRICS:
            assert m in scores, f"'{m}' missing. Got: {list(scores.keys())}"
        for m in _DETERMINISTIC:
            assert isinstance(scores.get(m), (int, float)), f"'{m}' = {scores.get(m)!r}"

        for k, v in sorted(scores.items()):
            print(f"  {k}: {v}")
        print(f"\nCSV PASSED - {len(scores)} metrics")

    def test_all_scoring_paths_covered(self):
        """Verify _TEST_METRICS covers every scoring code path."""
        from evaluation.scoring import _SCORE_SIGNATURES
        tested = {sig for sig, mset in _SCORE_SIGNATURES.items() if mset & set(_TEST_METRICS)}
        untested = set(_SCORE_SIGNATURES.keys()) - tested - {"metadata_sql", "metadata_data"}
        assert not untested, f"Untested paths: {untested}"


# ====================== RAG PIPELINE TESTS ======================

@pytest.fixture(scope="class")
def rag_server(tmp_path_factory):
    proc, db_path, base_url = _start_server(tmp_path_factory.mktemp("rag_test"), 18802)
    yield proc, db_path, base_url
    _stop_server(proc)


@pytest.mark.slow
@pytest.mark.integration
class TestRAGPipelineExperiment:

    def test_rag_pipeline_experiment(self, rag_server):
        """Full RAG: upload doc -> chunk -> embed -> rag config -> experiment."""
        proc, db_path, base_url = rag_server

        # 1. Project
        pid = requests.post(f"{base_url}/api/projects", json={"name": "RAG Test"}).json()["id"]
        print(f"\nRAG experiment: project={pid}")

        # 2. Upload document
        resp = requests.post(
            f"{base_url}/api/projects/{pid}/documents",
            files={"file": ("rag.txt", _DOC_TEXT.encode(), "text/plain")},
        )
        assert resp.status_code == 201, resp.text
        print(f"  doc uploaded")

        # 3. Chunk config + generate
        resp = requests.post(
            f"{base_url}/api/projects/{pid}/chunk-configs",
            json={"name": "chunks", "method": "fixed_overlap", "params": {"chunk_size": 200, "overlap": 20}},
        )
        assert resp.status_code == 201, resp.text
        ccid = resp.json()["id"]

        resp = requests.post(f"{base_url}/api/projects/{pid}/chunk-configs/{ccid}/generate")
        assert resp.status_code == 200, resp.text
        print(f"  {resp.json()['total_chunks']} chunks generated")

        # 4. Embedding config + embed
        resp = requests.post(
            f"{base_url}/api/projects/{pid}/embedding-configs",
            json={"name": "emb", "type": "dense_openai", "model_name": "text-embedding-3-small", "params": {}},
        )
        assert resp.status_code == 201, resp.text
        ecid = resp.json()["id"]

        resp = requests.post(
            f"{base_url}/api/projects/{pid}/embedding-configs/{ecid}/embed",
            json={"chunk_config_id": ccid}, timeout=120,
        )
        assert resp.status_code == 200, resp.text
        print(f"  {resp.json().get('total_embedded', '?')} chunks embedded")

        # 5. RAG config
        resp = requests.post(
            f"{base_url}/api/projects/{pid}/rag-configs",
            json={
                "name": "rag", "embedding_config_id": ecid, "chunk_config_id": ccid,
                "search_type": "dense", "llm_model": "gpt-4o-mini", "top_k": 3,
                "response_mode": "single_shot",
            },
        )
        assert resp.status_code == 201, resp.text
        rcid = resp.json()["id"]
        print(f"  rag config created")

        # 6. Test set (insert manually — avoids slow async generation)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?,?,?)",
            (pid, "manual", json.dumps({"source": "test"})),
        )
        conn.commit()
        tsid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, reference_contexts, question_type, status) VALUES (?,?,?,?,?,?)",
            (tsid, "What is RAG and how does it reduce hallucination?",
             "RAG combines retrieval with generation and reduces hallucination by anchoring output in source material.",
             json.dumps(["RAG combines information retrieval with text generation."]),
             "manual", "approved"),
        )
        conn.commit()
        conn.close()
        print(f"  test set created")

        # 7. Create experiment (RAG path)
        resp = requests.post(
            f"{base_url}/api/projects/{pid}/experiments",
            json={"name": "rag-test", "test_set_id": tsid, "rag_config_id": rcid},
        )
        assert resp.status_code == 201, resp.text
        eid = resp.json()["id"]
        assert resp.json().get("bot_config_id") is None
        print(f"  experiment {eid} created (RAG path)")

        # 8. Run + poll
        print(f"  running with {len(_RAG_METRICS)} metrics...")
        _fire_and_poll(base_url, db_path, pid, eid, _RAG_METRICS)

        # 9. Verify
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM experiment_results WHERE experiment_id=?", (eid,)).fetchall()
        conn.close()

        assert len(rows) == 1
        scores = json.loads(rows[0]["metrics_json"])
        response = rows[0]["response"]
        contexts = json.loads(rows[0]["retrieved_contexts"]) if rows[0]["retrieved_contexts"] else []

        # RAG pipeline generates a response using retrieved contexts
        assert response and len(response) > 10, f"Expected generated answer, got: {response!r}"

        for m in _RAG_METRICS:
            assert m in scores, f"'{m}' missing"

        print(f"  answer: {response[:100]}...")
        print(f"  contexts: {len(contexts)} retrieved")
        for k, v in sorted(scores.items()):
            print(f"  {k}: {v}")
        print(f"\nRAG PASSED - response generated, {len(contexts)} contexts, {len(scores)} metrics")
