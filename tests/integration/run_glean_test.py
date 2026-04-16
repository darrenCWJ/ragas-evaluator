"""Standalone script to test all 23 metrics against a mock Glean API.

Usage:
    python tests/integration/run_glean_test.py
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

from evaluation.scoring import ALL_METRICS

# ── Fake Glean server ────────────────────────────────────────────────

GLEAN_RESPONSE = {
    "response": {
        "fragments": [
            {
                "text": (
                    "Retrieval-Augmented Generation (RAG) combines information "
                    "retrieval with text generation to produce accurate, "
                    "grounded answers."
                ),
            },
            {
                "text": "RAG reduces hallucination by anchoring output in real sources.",
                "citation": {
                    "sourceDocument": {
                        "title": "RAG Overview",
                        "url": "https://wiki.example.com/rag",
                        "datasource": "confluence",
                        "container": "Wiki",
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
                    "grounded responses."
                ),
                "datasource": "google_drive",
                "container": "Eng Docs",
            },
            {
                "title": "Reducing Hallucination",
                "url": "https://docs.example.com/hallucination",
                "snippet": (
                    "By anchoring output in real source material, RAG "
                    "significantly reduces hallucination compared to "
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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(GLEAN_RESPONSE).encode())

    def log_message(self, *args):
        pass


def _find_free_port() -> int:
    """Find a free TCP port by briefly binding to port 0."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    glean_port = _find_free_port()
    app_port = _find_free_port()

    # Start fake Glean
    glean_srv = HTTPServer(("127.0.0.1", glean_port), FakeGleanHandler)
    threading.Thread(target=glean_srv.serve_forever, daemon=True).start()
    print(f"Fake Glean on {glean_port}")

    # Start app server
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test.db")
    env = {
        **os.environ,
        "DATABASE_PATH": db_path,
        "CHROMADB_PATH": os.path.join(tmp, "chroma"),
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(app_port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{app_port}"
    for _ in range(60):
        try:
            if requests.get(f"{base}/api/health", timeout=2).ok:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        out = proc.stdout.read().decode() if proc.stdout else ""
        print(f"Server failed to start:\n{out[:2000]}")
        sys.exit(1)
    print(f"App server on {app_port}")

    try:
        _run_test(base, db_path, glean_port)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        glean_srv.shutdown()


def _run_test(base, db_path, glean_port):
    all_metrics = list(ALL_METRICS)

    # Setup project + bot config
    pid = requests.post(f"{base}/api/projects", json={"name": "Glean Full Test"}).json()["id"]
    bcid = requests.post(f"{base}/api/projects/{pid}/bot-configs", json={
        "name": "Mock Glean",
        "connector_type": "glean",
        "config_json": {
            "api_key": "test-key",
            "base_url": f"http://127.0.0.1:{glean_port}",
        },
    }).json()["id"]
    print(f"project={pid}, bot_config={bcid}")

    # Test set with 2 questions
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?,?,?)",
        (pid, "ts", "{}"),
    )
    conn.commit()
    tsid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Q1: standard RAG question
    conn.execute(
        "INSERT INTO test_questions (test_set_id, question, reference_answer, "
        "reference_contexts, question_type, status) VALUES (?,?,?,?,?,?)",
        (
            tsid,
            "What is RAG and how does it reduce hallucination?",
            "RAG combines retrieval with generation and reduces hallucination "
            "by anchoring output in source material.",
            json.dumps([
                "RAG is a technique that combines retrieval with generation.",
                "RAG reduces hallucination by anchoring output in real sources.",
            ]),
            "manual",
            "approved",
        ),
    )

    # Q2: SQL/data domain question with metadata
    conn.execute(
        "INSERT INTO test_questions (test_set_id, question, reference_answer, "
        "reference_contexts, question_type, status, metadata_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            tsid,
            "Show users after 2024",
            "SELECT * FROM users WHERE created_at > '2024-01-01'",
            json.dumps(["Users table has registration data."]),
            "manual",
            "approved",
            json.dumps({
                "reference_sql": "SELECT * FROM users WHERE created_at > '2024-01-01'",
                "schema_contexts": [
                    "CREATE TABLE users (id INT, name TEXT, created_at TIMESTAMP)"
                ],
                "reference_data": "id,name\n1,Alice\n2,Bob",
            }),
        ),
    )
    conn.commit()
    conn.close()
    print(f"test_set={tsid} (2 questions)")

    # Create experiment
    eid = requests.post(f"{base}/api/projects/{pid}/experiments", json={
        "name": "glean-all",
        "test_set_id": tsid,
        "bot_config_id": bcid,
    }).json()["id"]
    print(f"experiment={eid}")

    # Run ALL metrics
    rubrics = {
        "accuracy": "Is the answer accurate?",
        "completeness": "Is it complete?",
    }
    print(f"Running {len(all_metrics)} metrics...")
    resp = requests.post(
        f"{base}/api/projects/{pid}/experiments/{eid}/run",
        json={"metrics": all_metrics, "concurrency": 1, "rubrics": rubrics},
        timeout=10,
    )
    print(f"Run: {resp.status_code} {resp.json()}")

    # Poll DB
    for i in range(240):  # 20 min max
        time.sleep(5)
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        exp = c.execute("SELECT status FROM experiments WHERE id=?", (eid,)).fetchone()
        cnt = c.execute(
            "SELECT COUNT(*) as n FROM experiment_results WHERE experiment_id=?",
            (eid,),
        ).fetchone()
        c.close()
        st, n = exp["status"], cnt["n"]
        if i % 6 == 0 or st in ("completed", "failed"):
            print(f"  [{(i+1)*5}s] status={st} results={n}")
        if st in ("completed", "failed"):
            break

    # Read results
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    exp = c.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    print(f"\nFinal status: {exp['status']}")

    rows = c.execute(
        "SELECT * FROM experiment_results WHERE experiment_id=? ORDER BY test_question_id",
        (eid,),
    ).fetchall()
    print(f"Total result rows: {len(rows)}")

    all_scored = set()
    for i, r in enumerate(rows):
        scores = json.loads(r["metrics_json"])
        all_scored |= set(scores.keys())
        meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        citations = meta.get("citations", [])
        contexts = json.loads(r["retrieved_contexts"]) if r["retrieved_contexts"] else []

        print(f"\nQ{i+1}:")
        print(f"  answer: {(r['response'] or '')[:100]}...")
        print(f"  citations: {len(citations)}, contexts: {len(contexts)}")
        scored_count = sum(1 for v in scores.values() if v is not None)
        none_count = sum(1 for v in scores.values() if v is None)
        print(f"  metrics: {len(scores)} total, {scored_count} scored, {none_count} none")
        for k, v in sorted(scores.items()):
            print(f"    {k}: {v}")
    c.close()

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Requested: {len(all_metrics)} metrics")
    print(f"Scored (union across questions): {len(all_scored)} metrics")
    missing = set(all_metrics) - all_scored
    if missing:
        print(f"MISSING: {missing}")
        sys.exit(1)
    else:
        print(f"ALL {len(all_metrics)} METRICS PRESENT!")

    # Deterministic checks
    deterministic = ["bleu_score", "rouge_score", "chrf_score", "exact_match",
                     "non_llm_string_similarity", "string_presence"]
    if rows:
        q1_scores = json.loads(rows[0]["metrics_json"])
        for m in deterministic:
            val = q1_scores.get(m)
            if not isinstance(val, (int, float)):
                print(f"FAIL: deterministic metric '{m}' = {val!r} (expected numeric)")
                sys.exit(1)
        print(f"All {len(deterministic)} deterministic metrics are numeric: PASS")

    print("\nTEST PASSED")


if __name__ == "__main__":
    main()
