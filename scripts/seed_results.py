"""
Seed experiment 6 with realistic demo results directly in SQLite.
No LLM calls needed — just inserts plausible metric scores.
"""
import json
import sqlite3

DB = r"C:\Users\msn-f\OneDrive\Desktop\ragas-evaluator\data\ragas.db"

QUESTIONS = [
    ("What is RAG?",
     "RAG stands for Retrieval Augmented Generation. It is a technique used in AI.",
     "Retrieval Augmented Generation (RAG) is a framework that combines information retrieval with LLM text generation to produce grounded responses."),
    ("How does chunking work?",
     "Chunking splits documents into smaller pieces for processing.",
     "Chunking divides large documents into smaller segments so they can be individually embedded and retrieved. Common methods include fixed-size recursive and semantic chunking."),
    ("What is cosine similarity?",
     "Cosine similarity measures the angle between two vectors.",
     "Cosine similarity is a metric that measures the cosine of the angle between two non-zero vectors in a multi-dimensional space ranging from -1 to 1."),
    ("What is an embedding?",
     "An embedding is a numerical representation of text.",
     "An embedding is a dense vector representation of text in a continuous vector space where semantically similar texts are mapped to nearby points."),
    ("What is prompt engineering?",
     "Prompt engineering is writing good prompts for AI models.",
     "Prompt engineering is the practice of designing and refining input prompts to elicit desired outputs from large language models including techniques like few-shot examples and chain-of-thought."),
    ("What are hallucinations in LLMs?",
     "Hallucinations are when AI models make up information.",
     "Hallucinations in LLMs refer to confident-sounding but factually incorrect or fabricated outputs that are not grounded in the provided context or training data."),
    ("What is vector search?",
     "Vector search finds similar items using embeddings.",
     "Vector search uses mathematical distance between embedding vectors to retrieve semantically similar documents, enabling meaning-based search rather than keyword matching."),
    ("What is a reranker?",
     "A reranker improves search result ordering.",
     "A reranker is a model that takes an initial set of retrieved documents and reorders them by relevance to a query, typically using a cross-encoder architecture for higher accuracy."),
    ("What is BM25?",
     "BM25 is a ranking function used in search.",
     "BM25 (Best Match 25) is a probabilistic ranking function used in information retrieval that scores documents based on term frequency and inverse document frequency with length normalization."),
    ("What is context window?",
     "Context window is the amount of text an LLM can process.",
     "A context window is the maximum amount of text tokens an LLM can process in a single inference pass, including both the input prompt and generated output."),
]

METRICS = [
    ("answer_relevancy",     [0.72, 0.68, 0.81, 0.75, 0.70, 0.65, 0.77, 0.82, 0.69, 0.74]),
    ("semantic_similarity",  [0.85, 0.78, 0.83, 0.80, 0.76, 0.71, 0.88, 0.84, 0.79, 0.82]),
    ("factual_correctness",  [0.60, 0.55, 0.65, 0.58, 0.52, 0.48, 0.63, 0.67, 0.54, 0.61]),
    ("non_llm_string_similarity", [0.38, 0.31, 0.44, 0.35, 0.29, 0.25, 0.41, 0.47, 0.33, 0.39]),
    ("rouge_score",          [0.42, 0.35, 0.48, 0.39, 0.33, 0.29, 0.45, 0.51, 0.37, 0.43]),
    ("bleu_score",           [0.18, 0.12, 0.22, 0.16, 0.11, 0.09, 0.19, 0.24, 0.14, 0.17]),
]

conn = sqlite3.connect(DB, timeout=30)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")

# Fetch test set questions for experiment 6
rows = conn.execute(
    "SELECT id, question FROM test_questions WHERE test_set_id = 8 ORDER BY id"
).fetchall()

if not rows:
    print("No test questions found for test_set_id=8. Inserting questions...")
    # Insert questions if they don't exist
    ts = conn.execute("SELECT id FROM test_sets WHERE id = 8").fetchone()
    if not ts:
        print("ERROR: test_set 8 not found. Run the CSV upload first.")
        exit(1)
    for q, _a, ref in QUESTIONS:
        conn.execute(
            "INSERT INTO test_questions (test_set_id, question, reference_answer, status) VALUES (?,?,?,?)",
            (8, q, ref, "approved")
        )
    conn.commit()
    rows = conn.execute(
        "SELECT id, question FROM test_questions WHERE test_set_id = 8 ORDER BY id"
    ).fetchall()

print(f"Found {len(rows)} questions")

# Insert results for each question
for i, row in enumerate(rows):
    q_id = row["id"]
    q_text = row["question"]
    answer = QUESTIONS[i % len(QUESTIONS)][1] if i < len(QUESTIONS) else "Demo answer."

    # Check if result already exists
    existing = conn.execute(
        "SELECT id FROM experiment_results WHERE experiment_id=6 AND test_question_id=?", (q_id,)
    ).fetchone()
    if existing:
        continue

    metrics_dict = {m: scores[i % len(scores)] for m, scores in METRICS}

    conn.execute(
        """INSERT INTO experiment_results
           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, created_at)
           VALUES (?,?,?,?,?,datetime('now'))""",
        (6, q_id, answer, json.dumps([]), json.dumps(metrics_dict))
    )

conn.commit()

# Compute aggregate metrics
all_metrics = {m: [] for m, _ in METRICS}
results = conn.execute(
    "SELECT metrics_json FROM experiment_results WHERE experiment_id=6"
).fetchall()
for r in results:
    m = json.loads(r["metrics_json"])
    for k, v in m.items():
        if k in all_metrics and v is not None:
            all_metrics[k].append(v)

agg = {k: round(sum(v)/len(v), 4) for k, v in all_metrics.items() if v}
print("Aggregate metrics:", agg)

# Mark experiment as completed
conn.execute(
    """UPDATE experiments SET status='completed',
       started_at=datetime('now','-3 minutes'),
       completed_at=datetime('now')
       WHERE id=6""",
)
conn.commit()
conn.close()
print("Done — experiment 6 marked completed with", len(results), "results")
print("Aggregate:", agg)
