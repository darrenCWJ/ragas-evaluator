"""Integration test: mock Glean API → experiment run with ALL metrics.

Spins up a fake Glean HTTP server that returns realistic responses,
then runs a full experiment through the real app server. No real
Glean API key needed.

    pytest tests/integration/test_glean_experiment.py -v -s
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest
import requests

from evaluation.scoring import ALL_METRICS

MAX_WAIT = 600
POLL_INTERVAL = 5

_ALL_METRICS = list(ALL_METRICS)

_DETERMINISTIC = [
    "bleu_score", "rouge_score", "chrf_score", "exact_match",
    "non_llm_string_similarity", "string_presence",
]

_TEST_RUBRICS = {
    "accuracy": "Does the answer accurately describe what RAG is and how it reduces hallucination?",
    "completeness": "Does the answer cover both retrieval and generation aspects of RAG?",
}

_GLEAN_RESPONSE = {
    "response": {
        "fragments": [
            {
                "text": (
                    "Retrieval-Augmented Generation (RAG) combines information "
                    "retrieval with text generation. It retrieves relevant "
                    "documents from a knowledge base and uses them as context "
                    "to produce accurate, grounded answers."
                ),
            },
            {
                "text": "RAG reduces hallucination by anchoring output in real sources.",
                "citation": {
                    "sourceDocument": {
                        "title": "RAG Overview - Internal Wiki",
                        "url": "https://wiki.example.com/rag-overview",
                        "datasource": "confluence",
                        "container": "Engineering Wiki",
                    }
                },
            },
        ],
    },
    "chat_result": {
        "sources": [
            {
                "title": "RAG Architecture Guide",
                "url": "https://docs.example.com/rag-arch",
                "snippet": (
                    "RAG is a technique that combines retrieval with generation. "
                    "It first retrieves relevant documents, then generates "
                    "grounded responses from them."
                ),
                "datasource": "google_drive",
                "container": "Engineering Docs",
            },
            {
                "title": "Reducing LLM Hallucination",
                "url": "https://docs.example.com/hallucination",
                "snippet": (
                    "By anchoring the model's output in real source material, "
                    "RAG significantly reduces hallucination compared to "
                    "standalone generation."
                ),
                "datasource": "confluence",
                "container": "ML Team",
            },
        ],
    },
}


class FakeGleanHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/rest/api/v1/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(content_length) if content_length else None
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(_GLEAN_RESPONSE).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_fake_glean(port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), FakeGleanHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            requests.post(
                f"http://127.0.0.1:{port}/rest/api/v1/chat",
                json={}, headers={"Authorization": "Bearer test"}, timeout=2,
            )
            return server
        except requests.ConnectionError:
            time.sleep(0.2)
    raise RuntimeError(f"Fake Glean server on port {port} did not start")


def _start_server(tmp_dir, port):
    db_path = str(tmp_dir / "test.db")
    env = {
        **os.environ,
        "DATABASE_PATH": db_path,
        "CHROMADB_PATH": str(tmp_dir / "chromadb"),
        "PYTHONUNBUFFERED": "1",
    }
    # Redirect stdout to devnull to prevent pipe buffer from blocking the server
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base_url}/api/health", timeout=2).ok:
                return proc, db_path, base_url
        except requests.ConnectionError:
            pass
        time.sleep(0.5)
    proc.kill()
    pytest.fail(f"Server on port {port} did not start within 30s")


def _stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _fire_and_poll(base_url, db_path, project_id, experiment_id, metrics,
                   rubrics=None, concurrency=1):
    """POST to /run, then poll DB until done."""
    run_body = {"metrics": metrics, "concurrency": concurrency}
    if rubrics:
        run_body["rubrics"] = rubrics

    resp = requests.post(
        f"{base_url}/api/projects/{project_id}/experiments/{experiment_id}/run",
        json=run_body, timeout=30,
    )
    assert resp.status_code == 200, f"Run failed: {resp.status_code} {resp.text}"
    print(f"  run started: {resp.json().get('status')}")

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
                    return
                if st == "failed":
                    pytest.fail("Experiment failed")
        except sqlite3.OperationalError:
            pass
        time.sleep(POLL_INTERVAL)

    pytest.fail(f"Timeout after {MAX_WAIT}s. status={last_st}, results={last_cnt}")


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.integration
class TestGleanExperiment:
    """End-to-end test: mock Glean API → bot config → experiment → all 23 metrics."""

    def test_glean_all_metrics(self, tmp_path):
        """Run ALL 23 metrics against a mock Glean bot connector."""
        glean_port = _find_free_port()
        app_port = _find_free_port()

        glean_srv = _start_fake_glean(glean_port)
        glean_url = f"http://127.0.0.1:{glean_port}"
        proc, db_path, base_url = _start_server(tmp_path, app_port)

        try:
            self._run_experiment(base_url, db_path, glean_url)
        finally:
            _stop_server(proc)
            glean_srv.shutdown()

    def _run_experiment(self, base_url, db_path, glean_url):
        pid = requests.post(f"{base_url}/api/projects", json={"name": "Glean All Metrics"}).json()["id"]
        print(f"\nGlean ALL metrics: project={pid}")

        resp = requests.post(
            f"{base_url}/api/projects/{pid}/bot-configs",
            json={
                "name": "Mock Glean", "connector_type": "glean",
                "config_json": {"api_key": "test-key", "base_url": glean_url},
            },
        )
        assert resp.status_code == 201, resp.text
        bcid = resp.json()["id"]
        assert resp.json()["returns_contexts"] is True
        print(f"  bot config: id={bcid}")

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?,?,?)",
            (pid, "glean-all-metrics", json.dumps({"source": "test"})),
        )
        conn.commit()
        tsid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, "
            "reference_contexts, question_type, status) VALUES (?,?,?,?,?,?)",
            (tsid, "What is RAG and how does it reduce hallucination?",
             "RAG combines retrieval with generation and reduces hallucination by anchoring output in source material.",
             json.dumps(["RAG is a technique that combines retrieval with generation.",
                         "RAG reduces hallucination by anchoring output in real sources."]),
             "manual", "approved"),
        )
        conn.commit()
        conn.close()
        print(f"  test set: id={tsid} (1 question)")

        resp = requests.post(
            f"{base_url}/api/projects/{pid}/experiments",
            json={"name": "glean-all-metrics-test", "test_set_id": tsid, "bot_config_id": bcid},
        )
        assert resp.status_code == 201, resp.text
        eid = resp.json()["id"]
        print(f"  experiment: id={eid}")

        print(f"  running {len(_ALL_METRICS)} metrics...")
        _fire_and_poll(base_url, db_path, pid, eid, metrics=_ALL_METRICS, rubrics=_TEST_RUBRICS)

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM experiment_results WHERE experiment_id=?", (eid,)).fetchall()
        conn.close()

        assert len(rows) == 1, f"Expected 1 result row, got {len(rows)}"

        row = rows[0]
        scores = json.loads(row["metrics_json"])
        response = row["response"]
        contexts = json.loads(row["retrieved_contexts"]) if row["retrieved_contexts"] else []
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        citations = meta.get("citations", [])

        assert response and len(response) > 20, f"No answer from Glean: {response!r}"
        assert "RAG" in response
        print(f"\n  answer: {response[:80]}...")

        assert len(citations) > 0, "Expected citations from Glean response"
        assert len(contexts) > 0, "Expected contexts from citation snippets"
        print(f"  citations: {len(citations)}, contexts: {len(contexts)}")

        for m in _ALL_METRICS:
            assert m in scores, f"'{m}' missing. Got: {sorted(scores.keys())}"

        for m in _DETERMINISTIC:
            assert isinstance(scores.get(m), (int, float)), f"'{m}' = {scores.get(m)!r}"

        scored = sum(1 for v in scores.values() if v is not None)
        nones = sum(1 for v in scores.values() if v is None)
        print(f"  metrics: {len(scores)} total, {scored} scored, {nones} none")
        for k, v in sorted(scores.items()):
            print(f"    {k}: {v}")

        print(f"\n  GLEAN ALL METRICS PASSED — {len(scores)} metrics, "
              f"{len(citations)} citations, {len(contexts)} contexts")

    def test_all_scoring_paths_covered(self):
        """Verify _ALL_METRICS covers every scoring code path."""
        from evaluation.scoring import _SCORE_SIGNATURES
        tested = {sig for sig, mset in _SCORE_SIGNATURES.items() if mset & set(_ALL_METRICS)}
        untested = set(_SCORE_SIGNATURES.keys()) - tested
        assert not untested, f"Untested scoring paths: {untested}"

    def test_glean_bot_config_crud(self, tmp_path):
        """Verify bot config CRUD for Glean type."""
        glean_port = _find_free_port()
        app_port = _find_free_port()

        glean_srv = _start_fake_glean(glean_port)
        glean_url = f"http://127.0.0.1:{glean_port}"
        proc, db_path, base_url = _start_server(tmp_path / "crud", app_port)

        try:
            pid = requests.post(f"{base_url}/api/projects", json={"name": "Glean CRUD"}).json()["id"]

            resp = requests.post(f"{base_url}/api/projects/{pid}/bot-configs", json={
                "name": "Glean with Agent", "connector_type": "glean",
                "config_json": {"api_key": "test-key", "base_url": glean_url, "agent_id": "agent-abc-123"},
            })
            assert resp.status_code == 201
            cfg = resp.json()
            assert cfg["config_json"]["agent_id"] == "agent-abc-123"
            assert cfg["returns_contexts"] is True
            print(f"\n  Create with agent_id: PASSED")

            resp = requests.get(f"{base_url}/api/projects/{pid}/bot-configs")
            assert resp.status_code == 200
            assert len(resp.json()) == 1
            print(f"  List: PASSED")

            resp = requests.put(f"{base_url}/api/projects/{pid}/bot-configs/{cfg['id']}",
                json={"name": "Updated Glean", "config_json": {"api_key": "new-key", "base_url": glean_url}})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated Glean"
            print(f"  Update: PASSED")

            resp = requests.get(f"{base_url}/api/projects/{pid}/bot-configs/{cfg['id']}")
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated Glean"
            print(f"  Get: PASSED")

            resp = requests.delete(f"{base_url}/api/projects/{pid}/bot-configs/{cfg['id']}")
            assert resp.status_code in (200, 204)
            print(f"  Delete: PASSED")

            resp = requests.get(f"{base_url}/api/projects/{pid}/bot-configs")
            assert len(resp.json()) == 0
            print(f"  GLEAN CRUD: ALL PASSED")
        finally:
            _stop_server(proc)
            glean_srv.shutdown()
