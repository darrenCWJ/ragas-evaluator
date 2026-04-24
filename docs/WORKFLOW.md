| [README](../README.md) | [Features Guide](FEATURES.md) | [Workflow](WORKFLOW.md) |
|---|---|---|

# Workflow Guide

End-to-end walkthrough: how to set up the platform, configure a RAG pipeline, generate a test set, run an experiment, and improve your bot.

---

## Overview

```
Setup → Create Project → Upload Docs → Configure Pipeline → Generate Test Set → Run Experiment → Analyze → Improve
```

Each step builds on the previous. You only do Setup once. Everything else is per-project and repeatable.

---

## Step 1 — Setup

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env — at minimum set:
#   OPENAI_API_KEY=sk-...
#   RAGAS_API_KEY=<random secret>   ← protects all endpoints
docker compose up --build
```

Open `http://localhost:8000` in your browser.

### Local development (no Docker)

```bash
# Backend
pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# KG Worker (optional — needed for KG-based test generation)
cd worker && pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY
uvicorn main:app --host 0.0.0.0 --port 3000 --reload

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

### Required environment variable

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Required. Used for embeddings, LLM calls, and evaluation metrics. |
| `RAGAS_API_KEY` | Recommended. Bearer token that protects all API endpoints. |
| `KG_WORKER_URL` | Optional. Set to `http://localhost:3000` if running the worker locally. |

---

## Step 2 — Create a Project

A **project** is an isolated workspace. All documents, configs, test sets, and experiments belong to one project.

1. Go to **Projects** in the sidebar.
2. Click **New Project** and give it a name.
3. Select the project to enter it.

> Create one project per bot or use case. This keeps experiments and results from different bots separate.

---

## Step 3 — Upload Documents

Your documents are the knowledge base the RAG system retrieves from.

1. Go to **Documents** inside the project.
2. Upload `.txt` or `.pdf` files (up to 50 MB each).
3. Optionally add a **context label** (e.g. "HR Policy", "Technical Docs") to help the embedding model distinguish document types.

> You can upload multiple files. All become part of the same retrieval index for this project.

---

## Step 4 — Configure the Chunking Pipeline

Chunking splits documents into retrievable pieces. Chunk quality directly affects retrieval quality.

1. Go to **Chunks**.
2. Click **New Chunk Config** and choose a strategy:

| Strategy | Best for |
|---|---|
| Recursive | General text — splits on paragraphs, then sentences |
| Markdown | Markdown files — splits on headers and sections |
| Token | Token-budget-aware splits for LLMs |
| Fixed overlap | Simple sliding windows |
| Parent-child | Hierarchical content (index small, retrieve large) |
| Semantic | Groups sentences by meaning |

3. (Optional) Add a second-stage strategy for a 2-step pipeline.
4. Click **Preview Chunks** to validate before committing.
5. Click **Save & Process** — chunks are stored in the database.

> If unsure, start with **Recursive**, chunk size 512, overlap 50. You can create multiple configs and compare them.

---

## Step 5 — Configure Embeddings

Embeddings convert chunks into vectors for semantic search.

1. Go to **Embeddings**.
2. Click **New Embedding Config** and pick a model:

| Model | Notes |
|---|---|
| `text-embedding-3-small` | Fast, cheap, good baseline (OpenAI) |
| `text-embedding-3-large` | Higher quality, more expensive (OpenAI) |
| SentenceTransformers | Local, no API cost, variety of models |

3. Choose a **search type**:

| Type | Notes |
|---|---|
| Dense | Pure vector similarity |
| Sparse (BM25) | Keyword matching |
| Hybrid | Combines both via Reciprocal Rank Fusion |

4. Click **Save & Embed** — vectors are stored in ChromaDB.

> Start with `text-embedding-3-small` + Hybrid search. Hybrid usually outperforms either alone.

---

## Step 6 — Configure the RAG Pipeline

A **RAG config** bundles chunking, embedding, search settings, and LLM into a single reproducible configuration.

1. Go to **RAG Config**.
2. Click **New Config** and fill in:
   - Chunk config (from Step 4)
   - Embedding config (from Step 5)
   - `top_k` — number of chunks to retrieve (start with 5)
   - LLM model (e.g. `gpt-4o-mini`)
   - System prompt — instructions for how the LLM should answer
   - Response mode: **Single-shot** (one call) or **Multi-step** (iterative refinement)
3. Click **Test Query** to run a single question and inspect the retrieved context and answer.
4. Save the config.

> The system prompt is important. Be explicit: "Answer only from the provided context. If unsure, say so."

---

## Step 7 — Set Up Personas (optional but recommended)

Personas define different user types whose questions will be generated. This ensures test diversity.

1. Go to **Personas**.
2. Click **Auto-Generate** to let the LLM create personas from your documents, or click **New Persona** to define one manually.
3. Each persona has a name, description, and question style (e.g. "technical detail-seeker", "non-technical manager").

> Without personas, the system uses a generic default. Custom personas improve question diversity significantly.

---

## Step 8 — Generate a Test Set

A **test set** is a collection of question–answer pairs used to evaluate the RAG pipeline.

1. Go to **Test Sets**.
2. Click **New Test Set**.
3. Choose a generation method:

| Method | When to use |
|---|---|
| **Direct** | Quick start. Questions generated directly from chunks. |
| **KG-based (chunks)** | Better quality. Builds a knowledge graph from chunks first, then generates grounded questions. Requires KG Worker. |
| **KG-based (documents)** | Same as above but uses raw documents instead of chunks. |

4. Select personas and set the target question count (20–100 is a good starting range).
5. Click **Generate** — this may take a few minutes, especially for KG-based generation.
6. Review generated questions in the **approval workflow**:
   - **Approve** — include in experiments
   - **Edit** — fix the question or reference answer
   - **Reject** — exclude from experiments

> Aim for at least 20 approved questions for meaningful metric aggregates. Reject any that are ambiguous or have wrong reference answers.

---

## Step 9 — Run an Experiment

An **experiment** runs your approved test questions against a RAG config (or external bot) and scores every answer.

1. Go to **Experiments**.
2. Click **New Experiment**.
3. Choose what to test:
   - **Internal RAG config** — tests your configured pipeline
   - **External bot** — tests an OpenAI, Claude, DeepSeek, Gemini, Glean, custom HTTP, or CSV bot
4. Select a test set.
5. Choose which metrics to compute (or select all).
6. Click **Run** — progress streams in real time via SSE.

> First experiment: run all metrics so you get a full picture. Later experiments can run a subset for speed.

---

## Step 10 — Analyze Results

After the experiment completes:

1. Go to **Results** to see per-question scores and the aggregate metric table.
2. Go to **Suggestions** to see the rule-based analysis:
   - Each suggestion identifies a weak metric, diagnoses the likely cause, and proposes a config change.
3. Review individual question results to spot patterns (e.g. certain topics always scoring low).

### What the metrics tell you

| Low metric | Likely problem | Try |
|---|---|---|
| `context_recall` | Retrieval misses relevant chunks | Increase `top_k` or switch to hybrid search |
| `context_precision` | Too much irrelevant context | Decrease `top_k` or add reranking |
| `faithfulness` | LLM hallucinating beyond context | Strengthen system prompt grounding |
| `answer_relevancy` | Responses drift from the question | Enable multi-step retrieval |
| Both recall + precision low | Embedding mismatch for the domain | Switch embedding model |
| High variance across questions | Inconsistent chunk quality | Try a different chunking strategy |

---

## Step 11 — Apply Suggestions and Re-run

1. In **Suggestions**, click **Apply** on one or more suggestions.
2. The system creates a new RAG config with the suggested changes applied.
3. Run a new experiment with the same test set.
4. Go to **Compare** — select the two experiments to see per-metric deltas.

This is the **iterative improvement loop**:

```
Experiment → Analyze → Apply Suggestion → New Experiment → Compare → Repeat
```

---

## Optional Features

### External bot testing

If you want to evaluate a bot you don't control:

1. Go to **Bot Configs** and add a connector (OpenAI, Claude, DeepSeek, Gemini, Glean, custom HTTP, or CSV).
2. Run an experiment and select the bot connector instead of a RAG config.

This lets you benchmark your internal pipeline against an external bot using the same test set and metrics.

### Multi-LLM judge

For higher-confidence metric scores:

1. In experiment settings, enable **Multi-LLM Judge**.
2. Configure 2–3 judge models.
3. After the experiment, each metric shows a reliability score based on inter-judge agreement. Low agreement flags borderline cases for human review.

### Human annotation

To validate whether automated metrics reflect real quality:

1. Go to **Annotations** after an experiment.
2. The system samples 20% of results for you to manually rate.
3. After rating, view **Evaluator Accuracy** — how well automated metrics agree with human judgement.

### Source verification

If your bot returns citations:

1. Go to **Source Verification** after an experiment.
2. The system checks each cited URL for reachability and content alignment.
3. Citations are labelled: verified, hallucinated, inaccessible, or unverifiable.

### Custom metrics

To add domain-specific scoring criteria:

1. Go to **Custom Metrics**.
2. Define a metric of type: integer range, similarity, rubrics, or instance rubrics.
3. Custom metrics appear alongside built-in ones in experiment runs.

---

## Typical First Session (30 minutes)

| Time | Action |
|---|---|
| 0–5 min | Setup + create project + upload 2–3 documents |
| 5–10 min | Create a chunk config (recursive, 512/50) + process |
| 10–15 min | Create an embedding config (text-embedding-3-small, hybrid) + embed |
| 15–20 min | Create a RAG config + test a single query |
| 20–25 min | Generate a test set (direct, 30 questions) + approve |
| 25–30 min | Run first experiment (all metrics) + review suggestions |
