| [README](README.md) | [Features Guide](docs/FEATURES.md) | [Workflow Guide](docs/WORKFLOW.md) |
|---|---|---|

# Tribunal

**LLM-as-a-judge evaluation platform for RAG chatbots.**

## Problem Statement

As AI chatbots become increasingly accessible, more individuals and teams are building conversational bots for customer support, internal knowledge bases, education, and other domains. However, a critical gap remains: **how do you know if your bot is actually giving accurate, grounded answers?**

Most RAG (Retrieval-Augmented Generation) systems are deployed with minimal evaluation. Builders rely on manual spot-checking or anecdotal feedback, leaving systemic issues — hallucinations, poor retrieval, irrelevant responses — undetected until users complain.

Tribunal addresses that gap. It provides an **LLM-as-a-judge evaluation platform** that systematically tests a RAG pipeline, identifies where it falls short, and generates actionable suggestions to improve it.

## Design

### Core Idea

Rather than treating evaluation as a one-off check, Tribunal enables an **iterative improvement loop**:

1. **Configure** a RAG pipeline (chunking strategy, embedding model, retrieval mode, LLM)
2. **Generate** synthetic test questions from your documents using auto-generated or custom personas
3. **Run experiments** that evaluate every question against 20+ metrics
4. **Analyze results** with an AI-powered suggestion engine that pinpoints weak spots
5. **Apply suggestions** to create a new configuration and re-run — comparing before and after

### Architecture

```
                    +------------------+
                    |   React Web UI   |
                    +--------+---------+
                             |
                    +--------+---------+
                    |   FastAPI REST   |
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
  +-------+-------+  +------+------+  +--------+--------+
  |   Pipeline    |  |  Evaluation |  |    Database     |
  | chunking      |  | 20+ metrics |  | SQLite (local)  |
  | embedding     |  | scoring     |  | PostgreSQL      |
  | retrieval     |  | suggestions |  | projects        |
  | generation    |  | test gen    |  | configs         |
  | bot connectors|  | custom      |  | experiments     |
  | multi-LLM     |  | annotations |  | annotations     |
  +---------------+  +-------------+  +-----------------+
          |
  +-------+-------+
  |  KG Worker    |  (optional separate service)
  | build-kg      |  POST /build-kg
  | progress      |  GET  /progress/{project_id}
  | kg store      |  DELETE /kg/{project_id}
  +---------------+
```

The **KG Worker** is an optional sidecar service that offloads memory-intensive knowledge graph construction from the main app. Tribunal delegates via HTTP and polls for progress. Without a worker, KG builds run in-process.

### Suggestion Engine

The suggestion engine analyzes aggregate metric scores and per-question variance to produce targeted recommendations:

| Signal | Diagnosis | Suggestion |
|--------|-----------|------------|
| Low context recall | Retrieval misses relevant chunks | Increase `top_k` or switch to hybrid search |
| Low context precision | Too much irrelevant context retrieved | Decrease `top_k` or add reranking |
| Low faithfulness | LLM hallucinating beyond retrieved context | Strengthen system prompt grounding instructions |
| Low answer relevancy | Responses drift from the question | Enable multi-step retrieval mode |
| Both recall and precision low | Embedding model mismatch for the domain | Switch embedding model |
| High metric variance across questions | Inconsistent chunk quality | Try a different chunking strategy |

Each suggestion maps to a specific config field and can be applied directly from the UI to spawn a new experiment.

## Metrics

### RAG Metrics
| Metric | What it measures |
|---|---|
| `faithfulness` | Response alignment with source context |
| `answer_relevancy` | Answer pertinence to the question |
| `context_precision` | Retrieval accuracy |
| `context_recall` | Coverage of relevant context |
| `context_entities_recall` | Entity extraction completeness |
| `noise_sensitivity` | Robustness to irrelevant context |
| `response_groundedness` | Factual grounding in retrieved context |

### Natural Language Comparison
| Metric | What it measures |
|---|---|
| `semantic_similarity` | Embedding cosine similarity to reference answer |
| `non_llm_string_similarity` | Levenshtein / Hamming / Jaro distance |
| `factual_correctness` | Factual overlap with reference answer |
| `bleu_score` | N-gram precision |
| `rouge_score` | Recall-oriented n-gram overlap |
| `chrf_score` | Character n-gram F-score |
| `exact_match` | Exact string match |
| `string_presence` | Substring presence check |

### General Purpose
| Metric | What it measures |
|---|---|
| `aspect_critic` | Custom aspect evaluation (e.g. harmfulness, helpfulness) |
| `rubrics_score` | Rubric-based multi-dimensional scoring |
| `instance_rubrics` | Per-question rubric scoring |
| `summarization_score` | Summary quality evaluation |

### NVIDIA Metrics
| Metric | What it measures |
|---|---|
| `answer_accuracy` | Response correctness |
| `context_relevance` | Context appropriateness |

### SQL / Tabular Metrics
| Metric | What it measures |
|---|---|
| `datacompy_score` | SQL query result comparison |
| `sql_semantic_equivalence` | Semantic SQL query equivalence |

## Key Features

- **Persona-based test generation** — auto-generate diverse personas (fast: direct LLM call; full: KG-based) with configurable question styles, or define custom ones. Personas are saved and reusable across test sets.
- **Bot connectors** — test external bots (OpenAI, Claude, DeepSeek, Gemini, Glean, custom HTTP, CSV) with a unified evaluation framework.
- **Multi-LLM judge** — run evaluation metrics across multiple LLM judges simultaneously with chain-of-thought reasoning and claim-level annotations. Computes a reliability score based on inter-judge agreement; flags results where judges disagree.
- **Reranker support** — optional cross-encoder reranker applied after retrieval with configurable top-k cutoff.
- **Source verification** — automatically check bot-cited URLs for reachability and content alignment. Statuses: `verified`, `hallucinated`, `inaccessible`, `unverifiable`.
- **Human annotation** — deterministic 20% sample of experiment results for human review; computes evaluator accuracy against ground truth.
- **Custom metrics** — define project-specific evaluation criteria (integer range, similarity, rubrics, instance rubrics, criteria judge, reference judge) without code changes. Includes LLM-powered description refinement.
- **Experiment comparison & reporting** — per-metric deltas, experiment lineage tracking, time-series trends, project-level reports by bot type, CSV/JSON export.
- **KG visualization** — stream knowledge graph nodes and edges via SSE; inspect the graph structure built for test generation.
- **2-step chunking pipeline** — chain two chunking strategies sequentially (e.g., markdown split then recursive) with post-chunk quality filters.
- **Contextual prefix embedding** — prepend document-level context labels to chunk text before embedding for improved multi-corpus retrieval.

## Deployment

### Option A — Self-hosting (Docker, recommended)

```bash
cp .env.example .env
# Required: add OPENAI_API_KEY
# Recommended: set RAGAS_API_KEY to a strong random secret to protect endpoints
docker compose up --build
```

Tribunal is available at `http://localhost:8000`. Data (SQLite DB, vector store, uploaded docs) is persisted in `./data/`. To use a different port, set `PORT=9000` in your `.env`.

The docker-compose stack includes the **KG Worker** service. To run without it, use:

```bash
docker compose up --build --no-deps app
```

### Option B — Server deployment (Northflank + Neon)

Set these environment variables on your platform:

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Required — OpenAI API access |
| `DATABASE_URL` | PostgreSQL connection string (e.g. Neon) |
| `RAGAS_API_KEY` | Strong secret to protect all API endpoints |
| `PORT` | Set automatically by Northflank |
| `KG_WORKER_URLS` | Optional — comma-separated worker URLs (e.g. `http://kg-worker-1:3000,http://kg-worker-2:3000`) |

The Dockerfile builds the frontend and starts the app on `$PORT` (defaults to `3000`). Deploy the worker separately using `worker/Dockerfile` and point `KG_WORKER_URLS` at it.

### Option C — Local development (no Docker)

```bash
pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY

# Backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Worker (optional — separate terminal)
cd worker && pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY
uvicorn main:app --host 0.0.0.0 --port 3000 --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev  # dev server on :5173
```

### Authentication

Set `RAGAS_API_KEY` in your `.env` to require a Bearer token on all Tribunal API requests. Without it, all endpoints are publicly accessible — only skip this on trusted private networks.

```bash
# Generate a strong secret
openssl rand -hex 32
```

Once set, all API requests require: `Authorization: Bearer <your-key>`

### Private network deployments

If your bot or cited document sources are hosted on a private/internal network, set:

```bash
ALLOW_PRIVATE_ENDPOINTS=true
```

By default this is `false`, which blocks requests to private IP ranges to prevent SSRF attacks on internet-facing deployments. Only enable this when the app itself runs on a trusted private network.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required.** OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Optional. Enables Claude models as judges |
| `GOOGLE_API_KEY` | — | Optional. Enables Gemini models as judges |
| `RAGAS_API_KEY` | — | Bearer token auth; without it all endpoints are public |
| `DATABASE_URL` | — | PostgreSQL connection string; omit for SQLite |
| `KG_WORKER_URLS` | — | Comma-separated worker URLs for load-balanced KG builds |
| `KG_WORKER_URL` | — | Legacy single-worker URL (backward compat) |
| `KG_THREAD_MODE` | `false` | Run KG builds in a thread instead of subprocess |
| `ALLOW_PRIVATE_ENDPOINTS` | `false` | Allow requests to private IPs (disable SSRF protection) |
| `PORT` | `8000` | Server port |
| `CONTEXT_CHAR_BUDGET` | `100000` | Max characters of context sent to the LLM |
| `BOT_QUERY_TIMEOUT` | `120` | Seconds before a bot query times out |
| `KG_SUBPROCESS_TIMEOUT` | `86400` | Seconds before a KG build is killed (0 = no limit) |
| `MAX_UPLOAD_SIZE` | `52428800` | Max document upload size in bytes (50 MB) |
| `MAX_BASELINE_ROWS` | `1000` | Max rows per baseline CSV upload |
| `MAX_UPLOAD_QA_ROWS` | `2000` | Max rows per test set CSV/JSON upload |
| `DEFAULT_EVAL_MODEL` | `gpt-4o-mini` | Default LLM for evaluation |
| `MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD` | `0.6` | Min reliability score to include a judge in consensus |
| `MULTI_LLM_JUDGE_TEMP_MIN` | `0.3` | Lowest judge temperature |
| `MULTI_LLM_JUDGE_TEMP_MAX` | `0.75` | Highest judge temperature |

## Project Structure

```
├── app/                     # FastAPI application
│   ├── __init__.py          # App factory, middleware, lifespan
│   ├── models.py            # Pydantic request/response models
│   └── routes/              # Route modules (16 modules)
│       ├── projects.py      # Project CRUD, baselines, API config
│       ├── documents.py     # Document upload (PDF/TXT/DOCX)
│       ├── chunks.py        # Chunking configuration and preview
│       ├── embeddings.py    # Embedding configuration
│       ├── rag.py           # RAG config and single-query testing
│       ├── testsets.py      # Test set generation, KG endpoints, upload
│       ├── personas.py      # Persona CRUD and auto-generation
│       ├── experiments.py   # Experiment runner (SSE streaming)
│       ├── analyze.py       # Suggestions and config changes
│       ├── bot_configs.py   # External bot connector configs
│       ├── annotations.py   # Human annotation and evaluator accuracy
│       ├── reports.py       # Project-level reporting and trends
│       ├── custom_metrics.py # User-defined evaluation metrics
│       ├── multi_llm_judge.py # Multi-judge evaluation
│       └── health.py        # Health check endpoint
├── pipeline/                # RAG engine
│   ├── chunking.py          # 6 chunking strategies + 2-step pipeline
│   ├── embedding.py         # OpenAI + SentenceTransformers + contextual prefix
│   ├── vectorstore.py       # ChromaDB integration
│   ├── bm25.py              # BM25 sparse search
│   ├── rag.py               # Retrieval + generation (dense/sparse/hybrid/reranker)
│   └── llm.py               # Multi-provider LLM routing (OpenAI, Anthropic, Google)
├── evaluation/              # Metrics and analysis
│   ├── metrics/             # 23 metric modules
│   ├── scoring.py           # Metric orchestration
│   ├── suggestions.py       # Rule-based suggestion engine
│   └── testgen.py           # Synthetic test generation (persona-based)
├── worker/                  # KG Worker service (separate FastAPI app)
│   ├── main.py              # Worker app entrypoint
│   ├── routes.py            # 5 endpoints: /build-kg, /progress, /kg, /clear-build, /health
│   ├── config.py            # Worker config (concurrency, timeouts, paths)
│   ├── db/init.py           # Worker DB layer (KG tables, progress tracking)
│   ├── evaluation/metrics/testgen.py  # KG build functions
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── db/                      # Main app database layer
│   └── init.py              # Schema, migrations, queries
├── frontend/                # React + TypeScript + Tailwind SPA
│   └── src/
│       ├── pages/           # Setup, Build, Test, Experiment, Analyze
│       └── components/      # UI components per feature
├── tests/                   # pytest test suite
├── main.py                  # Uvicorn entrypoint
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Uvicorn |
| Database | SQLite (local / self-hosted), PostgreSQL (Neon / server) |
| LLM | OpenAI, Anthropic, Google GenAI (multi-provider) |
| Evaluation | Ragas 0.4+ |
| Embeddings | OpenAI text-embedding-3-small, SentenceTransformers |
| Vector store | ChromaDB |
| Sparse search | BM25 (rank-bm25) |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| Document parsing | pypdf (PDF), python-docx (DOCX) |
| Containerisation | Docker (multi-stage build), docker compose |
