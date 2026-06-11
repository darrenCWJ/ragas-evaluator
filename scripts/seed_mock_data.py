"""
Seed script - populates all 6 tabs with realistic mock data.
Run: python3 seed_mock_data.py
"""
import json
import sqlite3
import urllib.request
import urllib.error
import datetime
import random
import sys

BASE = "http://localhost:8000"
PROJECT_ID = 3
DB_PATH = "data/ragas.db"
PYTHON = sys.executable


def api(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  WARN {method} {path} => {e.code}: {err[:150]}")
        return None


def upload_csv(path, csv_text, fields):
    boundary = "MockBoundary99"
    body_parts = []
    for k, v in fields.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        )
    csv_part = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"questions.csv\"\r\n"
        f"Content-Type: text/csv\r\n\r\n"
    )
    end_part = f"\r\n--{boundary}--\r\n"
    body = "".join(body_parts).encode() + csv_part.encode() + csv_text.encode() + end_part.encode()

    url = f"{BASE}{path}"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  WARN POST {path} => {e.code}: {err[:250]}")
        return None


def ts(offset_hours=0):
    dt = datetime.datetime.now() - datetime.timedelta(hours=offset_hours)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# ── 1. CLEAN UP partial previous run ─────────────────────────────────────────
print("Cleaning up previous seed data...")
cur.execute("DELETE FROM suggestions WHERE experiment_id IN (SELECT id FROM experiments WHERE project_id=? AND name IN ('Dense RAG v1','Hybrid RAG + Reranker','GPT-4o Evaluation'))", (PROJECT_ID,))
cur.execute("DELETE FROM experiment_results WHERE experiment_id IN (SELECT id FROM experiments WHERE project_id=? AND name IN ('Dense RAG v1','Hybrid RAG + Reranker','GPT-4o Evaluation'))", (PROJECT_ID,))
cur.execute("DELETE FROM experiments WHERE project_id=? AND name IN ('Dense RAG v1','Hybrid RAG + Reranker','GPT-4o Evaluation')", (PROJECT_ID,))
cur.execute("DELETE FROM custom_metrics WHERE project_id=? AND name IN ('Completeness','Citation Quality','Technical Accuracy')", (PROJECT_ID,))
cur.execute("DELETE FROM personas WHERE project_id=? AND name IN ('Developer','Product Manager','Researcher')", (PROJECT_ID,))
cur.execute("DELETE FROM documents WHERE project_id=? AND filename IN ('rag_overview.pdf','chunking_strategies.md','embedding_models.txt','evaluation_metrics.pdf','llm_fundamentals.pdf')", (PROJECT_ID,))
con.commit()
print("  done")

# ── 2. CHUNK CONFIGS via API ──────────────────────────────────────────────────
print("\n-- Chunk configs --")
chunk_ids = {}
cur.execute("SELECT name, id FROM chunk_configs WHERE project_id=?", (PROJECT_ID,))
existing = {r[0]: r[1] for r in cur.fetchall()}

for cfg in [
    {"name": "Recursive 512", "method": "recursive", "params": {"chunk_size": 512, "chunk_overlap": 64}},
    {"name": "Recursive 256", "method": "recursive", "params": {"chunk_size": 256, "chunk_overlap": 32}},
    {"name": "Semantic Chunking", "method": "semantic", "params": {"breakpoint_threshold_type": "percentile", "breakpoint_threshold_amount": 95}},
]:
    if cfg["name"] in existing:
        chunk_ids[cfg["name"]] = existing[cfg["name"]]
        print(f"  skip {cfg['name']} (exists, id={existing[cfg['name']]})")
    else:
        r = api("POST", f"/api/projects/{PROJECT_ID}/chunk-configs", cfg)
        if r:
            chunk_ids[cfg["name"]] = r["id"]
            print(f"  + {cfg['name']} => id={r['id']}")

# ── 3. EMBEDDING CONFIGS via API ──────────────────────────────────────────────
print("\n-- Embedding configs --")
emb_ids = {}
cur.execute("SELECT name, id FROM embedding_configs WHERE project_id=?", (PROJECT_ID,))
existing_emb = {r[0]: r[1] for r in cur.fetchall()}

for cfg in [
    {"name": "OpenAI Small", "type": "dense_openai", "model_name": "text-embedding-3-small"},
    {"name": "OpenAI Large", "type": "dense_openai", "model_name": "text-embedding-3-large"},
]:
    if cfg["name"] in existing_emb:
        emb_ids[cfg["name"]] = existing_emb[cfg["name"]]
        print(f"  skip {cfg['name']} (exists)")
    else:
        r = api("POST", f"/api/projects/{PROJECT_ID}/embedding-configs", cfg)
        if r:
            emb_ids[cfg["name"]] = r["id"]
            print(f"  + {cfg['name']} => id={r['id']}")

# ── 4. RAG CONFIGS via API ────────────────────────────────────────────────────
print("\n-- RAG configs --")
rag_ids = {}
cur.execute("SELECT name, id FROM rag_configs WHERE project_id=?", (PROJECT_ID,))
existing_rag = {r[0]: r[1] for r in cur.fetchall()}

c_id = list(chunk_ids.values())[0] if chunk_ids else None
e_id = list(emb_ids.values())[0] if emb_ids else None

if c_id and e_id:
    for cfg in [
        {
            "name": "Dense Search k=5",
            "embedding_config_id": e_id, "chunk_config_id": c_id,
            "search_type": "dense", "llm_model": "gpt-4o-mini", "top_k": 5,
            "system_prompt": "You are a helpful RAG assistant. Use the provided context to answer questions accurately.",
            "response_mode": "single_shot",
        },
        # Hybrid needs a sparse (BM25) embedding config — skip via API, insert directly below

        {
            "name": "Dense + Reranker",
            "embedding_config_id": e_id, "chunk_config_id": c_id,
            "search_type": "dense", "llm_model": "gpt-4o", "top_k": 10,
            "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2", "reranker_top_k": 5,
            "system_prompt": "You are a helpful RAG assistant. Use the provided context to answer questions accurately.",
            "response_mode": "single_shot",
        },
    ]:
        if cfg["name"] in existing_rag:
            rag_ids[cfg["name"]] = existing_rag[cfg["name"]]
            print(f"  skip {cfg['name']} (exists)")
        else:
            r = api("POST", f"/api/projects/{PROJECT_ID}/rag-configs", cfg)
            if r:
                rag_ids[cfg["name"]] = r["id"]
                print(f"  + {cfg['name']} => id={r['id']}")
    # Hybrid RAG — needs sparse BM25 config, insert directly into DB
    cur.execute("SELECT id FROM embedding_configs WHERE project_id=? AND type='bm25_sparse' LIMIT 1", (PROJECT_ID,))
    row = cur.fetchone()
    if not row:
        cur.execute("""
            INSERT INTO embedding_configs (project_id, name, type, model_name, params_json, created_at)
            VALUES (?,?,?,?,?,?)
        """, (PROJECT_ID, "BM25 Sparse", "bm25_sparse", "bm25", None, ts(48)))
        sparse_id = cur.lastrowid
        print(f"  + BM25 Sparse embedding => id={sparse_id}")
    else:
        sparse_id = row[0]
        print(f"  skip BM25 Sparse (exists, id={sparse_id})")

    if "Hybrid Search k=8" not in existing_rag:
        cur.execute("""
            INSERT INTO rag_configs (project_id, name, embedding_config_id, chunk_config_id,
                search_type, sparse_config_id, alpha, llm_model, top_k,
                system_prompt, response_mode, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (PROJECT_ID, "Hybrid Search k=8", e_id, c_id, "hybrid", sparse_id, 0.5,
              "gpt-4o-mini", 8,
              "You are a helpful RAG assistant. Use the provided context to answer questions accurately.",
              "single_shot", ts(47)))
        hybrid_rag_id = cur.lastrowid
        rag_ids["Hybrid Search k=8"] = hybrid_rag_id
        print(f"  + Hybrid Search k=8 => id={hybrid_rag_id}")
    else:
        rag_ids["Hybrid Search k=8"] = existing_rag["Hybrid Search k=8"]
        print(f"  skip Hybrid Search k=8 (exists)")
else:
    print("  no chunk/embedding ids available, using existing rag configs")
    for name, rid in existing_rag.items():
        rag_ids[name] = rid

# ── 5. BOT CONFIGS ────────────────────────────────────────────────────────────
print("\n-- Bot configs --")
cur.execute("SELECT name FROM bot_configs WHERE project_id=?", (PROJECT_ID,))
existing_bots = {r[0] for r in cur.fetchall()}

for cfg in [
    {"name": "GPT-4o Mini Bot", "connector_type": "openai", "config_json": {"model": "gpt-4o-mini", "temperature": 0.1}},
    {"name": "Claude Haiku Bot", "connector_type": "claude", "config_json": {"model": "claude-haiku-4-5-20251001", "temperature": 0.1}},
]:
    if cfg["name"] in existing_bots:
        print(f"  skip {cfg['name']} (exists)")
    else:
        r = api("POST", f"/api/projects/{PROJECT_ID}/bot-configs", cfg)
        if r:
            print(f"  + {cfg['name']} => id={r['id']}")

# ── 6. TEST SET via CSV upload ────────────────────────────────────────────────
print("\n-- Test set upload --")
cur.execute("SELECT id FROM test_sets WHERE project_id=? AND name='RAG Evaluation Q&A'", (PROJECT_ID,))
existing_ts = cur.fetchone()

test_set_id = None
if existing_ts:
    test_set_id = existing_ts[0]
    print(f"  skip (exists, id={test_set_id})")
else:
    csv_text = (
        "question,reference_answer,contexts\n"
        "What is RAG?,Retrieval Augmented Generation (RAG) is a framework that combines information retrieval with LLM text generation.,RAG retrieves relevant documents before generating a response.\n"
        "How does chunking work?,Chunking divides large documents into smaller segments for embedding and retrieval.,Documents are split into chunks for better retrieval.\n"
        "What is cosine similarity?,Cosine similarity measures the cosine of the angle between two vectors ranging from -1 to 1.,Cosine similarity is used to compare embedding vectors.\n"
        "What is an embedding?,An embedding is a dense vector representation of text where similar texts map to nearby vectors.,Embeddings enable semantic search over documents.\n"
        "What is prompt engineering?,Prompt engineering designs input prompts to guide LLM outputs using techniques like few-shot examples.,Prompts control LLM behavior and output quality.\n"
        "What are hallucinations in LLMs?,Hallucinations occur when LLMs generate factually incorrect information. RAG mitigates this with source documents.,Hallucinations are AI-generated false information.\n"
        "What is vector search?,Vector search finds semantically similar documents using embedding similarity rather than keyword matching.,Vector search uses embeddings for semantic retrieval.\n"
        "What is BM25?,BM25 is a probabilistic ranking function using term frequency and inverse document frequency.,BM25 is a classic keyword-based ranking algorithm.\n"
        "What is a knowledge graph?,A knowledge graph stores entities and relationships as nodes and edges for structured reasoning.,Knowledge graphs enable multi-hop reasoning.\n"
        "How does reranking work?,Reranking applies a cross-encoder to re-score initial retrieval results for better relevance ordering.,Reranking improves the ordering of retrieved documents.\n"
        "What is context window?,Context window is the maximum number of tokens an LLM can process in one call.,Context window limits how much text LLMs can use.\n"
        "What is hybrid search?,Hybrid search combines dense vector search with sparse BM25 retrieval for better coverage.,Hybrid search blends semantic and keyword retrieval.\n"
    )
    r = upload_csv(f"/api/projects/{PROJECT_ID}/test-sets/upload/preview", csv_text, {})
    if r:
        print(f"  preview: {r.get('total_rows')} rows")
        r2 = upload_csv(
            f"/api/projects/{PROJECT_ID}/test-sets/upload",
            csv_text,
            {
                "question_column": "question",
                "answer_column": "reference_answer",
                "contexts_column": "contexts",
                "name": "RAG Evaluation Q&A",
            },
        )
        if r2:
            test_set_id = r2.get("id")
            print(f"  + test set id={test_set_id}, {r2.get('question_count')} questions")

# ── 7. LOAD QUESTION IDs ──────────────────────────────────────────────────────
if test_set_id:
    cur.execute("SELECT id, question FROM test_questions WHERE test_set_id=?", (test_set_id,))
else:
    cur.execute("SELECT id, question FROM test_questions LIMIT 12")
qs = cur.fetchall()
print(f"\n  Using {len(qs)} questions for experiments")

exp_test_set_id = test_set_id or 8

# ── 8. EXPERIMENTS + RESULTS via direct DB ───────────────────────────────────
print("\n-- Experiments --")

# Resolve IDs
cur.execute("SELECT id FROM chunk_configs WHERE project_id=? LIMIT 1", (PROJECT_ID,))
row = cur.fetchone(); cc_id = row[0] if row else None
cur.execute("SELECT id FROM embedding_configs WHERE project_id=? LIMIT 1", (PROJECT_ID,))
row = cur.fetchone(); ec_id = row[0] if row else None
cur.execute("SELECT id FROM rag_configs WHERE project_id=? LIMIT 1", (PROJECT_ID,))
row = cur.fetchone(); rc_id = row[0] if row else None

questions_data = [
    (
        "What is RAG?",
        "RAG (Retrieval Augmented Generation) grounds LLM responses by first retrieving relevant source documents, then generating an answer from them. This reduces hallucinations.",
        "Retrieval Augmented Generation (RAG) is a framework combining information retrieval with LLM generation.",
        {"answer_relevancy": 0.88, "semantic_similarity": 0.92, "factual_correctness": 0.81, "context_precision": 0.84, "context_recall": 0.79},
    ),
    (
        "How does chunking work?",
        "Chunking splits documents into smaller segments. Recursive chunking uses configurable size and overlap. Semantic chunking identifies natural breakpoints in text flow.",
        "Chunking divides large documents into smaller segments for embedding and retrieval.",
        {"answer_relevancy": 0.85, "semantic_similarity": 0.89, "factual_correctness": 0.77, "context_precision": 0.81, "context_recall": 0.75},
    ),
    (
        "What is cosine similarity?",
        "Cosine similarity measures the cosine of the angle between two vectors in a high-dimensional space, ranging from -1 to 1. Values near 1 indicate semantically similar texts.",
        "Cosine similarity measures the cosine of the angle between two vectors.",
        {"answer_relevancy": 0.91, "semantic_similarity": 0.93, "factual_correctness": 0.84, "context_precision": 0.88, "context_recall": 0.82},
    ),
    (
        "What is an embedding?",
        "An embedding is a dense numerical vector encoding semantic meaning. Similar texts produce similar vectors, enabling semantic search and comparison.",
        "An embedding is a dense vector representation mapping text to a continuous vector space.",
        {"answer_relevancy": 0.87, "semantic_similarity": 0.91, "factual_correctness": 0.80, "context_precision": 0.85, "context_recall": 0.78},
    ),
    (
        "What is prompt engineering?",
        "Prompt engineering crafts and optimizes prompts to guide LLM behavior. Techniques include chain-of-thought, few-shot examples, and role assignment.",
        "Prompt engineering designs input prompts to guide LLM outputs.",
        {"answer_relevancy": 0.83, "semantic_similarity": 0.87, "factual_correctness": 0.74, "context_precision": 0.79, "context_recall": 0.72},
    ),
    (
        "What are hallucinations in LLMs?",
        "LLM hallucinations are confident but incorrect or fabricated outputs. RAG mitigates this by anchoring responses to retrieved source documents.",
        "Hallucinations occur when LLMs generate factually incorrect information.",
        {"answer_relevancy": 0.80, "semantic_similarity": 0.85, "factual_correctness": 0.70, "context_precision": 0.77, "context_recall": 0.68},
    ),
    (
        "What is vector search?",
        "Vector search finds documents by computing similarity between query and document embeddings, enabling semantic retrieval across large corpora.",
        "Vector search finds similar documents using embedding similarity.",
        {"answer_relevancy": 0.90, "semantic_similarity": 0.94, "factual_correctness": 0.83, "context_precision": 0.87, "context_recall": 0.81},
    ),
    (
        "What is BM25?",
        "BM25 (Best Match 25) scores documents using term frequency and inverse document frequency with length normalization. It is the gold standard for keyword-based retrieval.",
        "BM25 is a probabilistic ranking function using term frequency and inverse document frequency.",
        {"answer_relevancy": 0.86, "semantic_similarity": 0.90, "factual_correctness": 0.79, "context_precision": 0.83, "context_recall": 0.76},
    ),
    (
        "What is a knowledge graph?",
        "A knowledge graph represents entities and relationships as nodes and edges. It enables structured reasoning and multi-hop question answering beyond flat document retrieval.",
        "A knowledge graph stores entities and relationships for structured reasoning.",
        {"answer_relevancy": 0.84, "semantic_similarity": 0.88, "factual_correctness": 0.75, "context_precision": 0.80, "context_recall": 0.73},
    ),
    (
        "How does reranking work?",
        "Reranking applies a cross-encoder model as a second-stage filter over an initial candidate set from retrieval, producing a relevance-ordered result list.",
        "Reranking re-scores initial retrieval results using a cross-encoder.",
        {"answer_relevancy": 0.89, "semantic_similarity": 0.92, "factual_correctness": 0.82, "context_precision": 0.86, "context_recall": 0.80},
    ),
    (
        "What is context window?",
        "The context window is the maximum number of tokens an LLM can process per inference call. Larger windows allow more retrieved chunks to be included in the prompt.",
        "Context window limits how many tokens an LLM can process at once.",
        {"answer_relevancy": 0.82, "semantic_similarity": 0.86, "factual_correctness": 0.73, "context_precision": 0.78, "context_recall": 0.70},
    ),
    (
        "What is hybrid search?",
        "Hybrid search combines dense vector retrieval with sparse BM25 using a weighted alpha parameter. It captures both semantic meaning and exact keyword matches.",
        "Hybrid search combines dense and sparse retrieval for better coverage.",
        {"answer_relevancy": 0.88, "semantic_similarity": 0.91, "factual_correctness": 0.80, "context_precision": 0.84, "context_recall": 0.77},
    ),
]


def insert_experiment(name, model, status, h_start, h_end, rag_cfg, bot_cfg, ts_id, baseline_id=None):
    cur.execute("""
        INSERT INTO experiments (project_id, test_set_id, name, model, model_params_json,
            retrieval_config_json, chunk_config_id, embedding_config_id, rag_config_id,
            bot_config_id, baseline_experiment_id, status, started_at, completed_at, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        PROJECT_ID, ts_id, name, model, None, None,
        cc_id, ec_id, rag_cfg, bot_cfg, baseline_id, status,
        ts(h_start), ts(h_end) if status == "completed" else None, ts(h_start + 0.1),
    ))
    return cur.lastrowid


def insert_result(exp_id, q_id, question, resp, ref, metrics):
    cur.execute("""
        INSERT INTO experiment_results (experiment_id, test_question_id, response,
            retrieved_contexts, metrics_json, metadata_json, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (
        exp_id, q_id, resp,
        json.dumps([{"content": f"Context about: {question[:50]}. This document discusses retrieval and generation."}]),
        json.dumps(metrics), json.dumps({}), ts(1),
    ))


# Experiment 2 — Dense RAG v1
exp2_id = insert_experiment("Dense RAG v1", "gpt-4o-mini", "completed", 48, 46, rc_id, None, exp_test_set_id, baseline_id=6)
for i, (q, resp, ref, metrics) in enumerate(questions_data):
    q_id = qs[i][0] if i < len(qs) else (86 + i)
    insert_result(exp2_id, q_id, q, resp, ref, metrics)
print(f"  + Dense RAG v1 => id={exp2_id}")

# Experiment 3 — Hybrid RAG (improved)
random.seed(42)
improved = [
    {k: min(1.0, round(v + random.uniform(0.04, 0.09), 3)) for k, v in m.items()}
    for _, _, _, m in questions_data
]
exp3_id = insert_experiment("Hybrid RAG + Reranker", "gpt-4o-mini", "completed", 24, 22, rc_id, None, exp_test_set_id, baseline_id=exp2_id)
for i, (q, resp, ref, _) in enumerate(questions_data):
    q_id = qs[i][0] if i < len(qs) else (86 + i)
    insert_result(exp3_id, q_id, q, resp, ref, improved[i])
print(f"  + Hybrid RAG + Reranker => id={exp3_id}")

# Experiment 4 — Pending
exp4_id = insert_experiment("GPT-4o Full Eval", "gpt-4o", "pending", 1, 1, rc_id, None, exp_test_set_id)
print(f"  + GPT-4o Full Eval (pending) => id={exp4_id}")

# ── 9. AGGREGATE METRICS (computed dynamically by API from metrics_json) ──────
print("\n-- Aggregate metrics computed dynamically by API from metrics_json --")

# ── 10. SUGGESTIONS ───────────────────────────────────────────────────────────
print("\n-- Suggestions --")
suggestions = [
    (exp2_id, "retrieval", "Low context_recall (avg 0.76)", "Increase top_k from 5 to 8 to retrieve more candidate chunks per query", "high", "top_k", "8"),
    (exp2_id, "chunking", "Chunk size may be too coarse for precise retrieval", "Reduce chunk_size from 512 to 256 tokens for finer-grained segments", "medium", "chunk_size", "256"),
    (exp2_id, "model", "factual_correctness below 0.80 across 8 questions", "Switch to gpt-4o for improved factual grounding", "medium", "llm_model", "gpt-4o"),
    (exp2_id, "retrieval", "Dense-only search misses keyword-specific queries", "Enable hybrid search (alpha=0.5) combining BM25 and dense retrieval", "high", "search_type", "hybrid"),
    (exp3_id, "prompt", "Some responses lack attribution to source passages", "Add citation instruction to system prompt: 'Cite source chunk numbers in your answer'", "low", "system_prompt", None),
    (exp3_id, "retrieval", "context_precision 0.86 — some irrelevant chunks included", "Lower reranker_top_k from 5 to 3 to filter more aggressively", "medium", "reranker_top_k", "3"),
]
for exp_id, cat, signal, sugg, priority, cf, sv in suggestions:
    cur.execute("""
        INSERT INTO suggestions (experiment_id, category, signal, suggestion, priority, config_field, suggested_value, implemented, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (exp_id, cat, signal, sugg, priority, cf, sv, 0, ts(20)))
print(f"  + {len(suggestions)} suggestions")

# ── 11. PERSONAS ──────────────────────────────────────────────────────────────
print("\n-- Personas --")
for name, role, style in [
    ("Developer", "A backend software engineer evaluating RAG for production deployment", "Technical, precise, asks about implementation details and performance"),
    ("Product Manager", "A non-technical stakeholder assessing RAG quality for business decisions", "Focuses on outcomes and business impact, uses plain language"),
    ("Researcher", "An ML researcher benchmarking retrieval and generation quality", "Rigorous and systematic, uses academic terminology"),
]:
    cur.execute("""
        INSERT INTO personas (project_id, name, role_description, question_style, created_at)
        VALUES (?,?,?,?,?)
    """, (PROJECT_ID, name, role, style, ts(100)))
print("  + 3 personas")

# ── 12. CUSTOM METRICS ────────────────────────────────────────────────────────
print("\n-- Custom metrics --")
for name, mtype, prompt, rubrics, mn, mx in [
    ("Completeness", "criteria_judge", "Rate whether the response fully addresses all parts of the question without omitting key details.", None, 0, 1),
    ("Citation Quality", "integer_range", "Score 1-5 how well the response cites and attributes source material.", None, 1, 5),
    ("Technical Accuracy", "rubrics", None,
     {"1": "Factually incorrect", "2": "Mostly wrong", "3": "Partially correct", "4": "Mostly accurate", "5": "Fully accurate"}, 1, 5),
]:
    cur.execute("""
        INSERT INTO custom_metrics (project_id, name, metric_type, prompt, rubrics_json, min_score, max_score, refined_prompt, few_shot_examples_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (PROJECT_ID, name, mtype, prompt, json.dumps(rubrics) if rubrics else None, mn, mx, None, None, ts(72)))
print("  + 3 custom metrics")

# ── 13. DOCUMENTS (metadata only, no file content needed for display) ─────────
print("\n-- Documents --")
for fname, ftype, label in [
    ("rag_overview.pdf", "pdf", "RAG Overview"),
    ("chunking_strategies.md", "md", "Chunking Guide"),
    ("embedding_models.txt", "txt", "Embedding Models"),
    ("evaluation_metrics.pdf", "pdf", "Evaluation Metrics"),
    ("llm_fundamentals.pdf", "pdf", "LLM Fundamentals"),
]:
    cur.execute("""
        INSERT INTO documents (project_id, filename, file_type, content, context_label, created_at)
        VALUES (?,?,?,?,?,?)
    """, (PROJECT_ID, fname, ftype, f"[Demo content for {fname}]", label, ts(96)))
print("  + 5 documents")

# ── 14. KNOWLEDGE GRAPH ───────────────────────────────────────────────────────
print("\n-- Knowledge graph --")
kg_nodes = [
    {"id": f"n{i}", "type": t, "label": l, "keyphrases": kp}
    for i, (t, l, kp) in enumerate([
        ("concept", "Retrieval Augmented Generation", ["RAG", "retrieval", "generation"]),
        ("concept", "Vector Embeddings", ["embeddings", "dense vectors", "semantic"]),
        ("concept", "Chunking Strategies", ["chunking", "recursive", "semantic split"]),
        ("concept", "BM25 Ranking", ["BM25", "keyword", "sparse retrieval"]),
        ("concept", "Cosine Similarity", ["cosine", "similarity", "vector distance"]),
        ("concept", "Knowledge Graph", ["graph", "entities", "relationships"]),
        ("concept", "Prompt Engineering", ["prompts", "few-shot", "chain-of-thought"]),
        ("concept", "Hallucinations", ["hallucination", "factual errors", "grounding"]),
        ("method", "Hybrid Search", ["hybrid", "alpha", "dense+sparse"]),
        ("method", "Reranking", ["reranker", "cross-encoder", "relevance scoring"]),
        ("method", "Context Window Management", ["context window", "tokens", "chunking"]),
        ("method", "Evaluation Metrics", ["RAGAS", "faithfulness", "relevancy"]),
    ])
]
kg_edges = [
    {"source": "n0", "target": "n1", "type": "uses", "score": 0.92},
    {"source": "n0", "target": "n2", "type": "requires", "score": 0.88},
    {"source": "n0", "target": "n7", "type": "mitigates", "score": 0.85},
    {"source": "n1", "target": "n4", "type": "computed_by", "score": 0.94},
    {"source": "n2", "target": "n3", "type": "alternative_to", "score": 0.79},
    {"source": "n8", "target": "n1", "type": "includes", "score": 0.90},
    {"source": "n8", "target": "n3", "type": "includes", "score": 0.87},
    {"source": "n9", "target": "n8", "type": "post_processes", "score": 0.83},
    {"source": "n5", "target": "n0", "type": "enhances", "score": 0.78},
    {"source": "n6", "target": "n7", "type": "reduces", "score": 0.82},
    {"source": "n11", "target": "n0", "type": "evaluates", "score": 0.91},
    {"source": "n10", "target": "n2", "type": "constrained_by", "score": 0.76},
]

kg_data = json.dumps({"nodes": kg_nodes, "edges": kg_edges})
chunks_hash = "mock_seed_hash_v1"

cur.execute("SELECT id FROM knowledge_graphs WHERE project_id=? AND chunks_hash=?", (PROJECT_ID, chunks_hash))
if not cur.fetchone():
    chunk_cfg_id = list(chunk_ids.values())[0] if chunk_ids else None
    cur.execute("""
        INSERT INTO knowledge_graphs (project_id, chunks_hash, chunk_config_id, kg_json,
            num_nodes, num_chunks, is_complete, completed_steps, total_steps, kg_source, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (PROJECT_ID, chunks_hash, chunk_cfg_id, kg_data, len(kg_nodes), 89, 1, 4, 4, "chunks", ts(12)))
    print(f"  + KG: {len(kg_nodes)} nodes, {len(kg_edges)} edges")
else:
    print("  skip (exists)")

con.commit()
con.close()

print("\nSeed complete. Project 3 'my-rag-bot' has data for all 6 tabs.")
print("Open http://localhost:5173/app/ and select project 'my-rag-bot'")
