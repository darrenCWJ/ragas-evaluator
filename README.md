| [README](README.md) | [Features Guide](docs/FEATURES.md) |
|---|---|

# Tribunal — RAG Evaluator

## Problem Statement

As AI chatbots become increasingly accessible, more individuals and teams are building conversational bots for customer support, internal knowledge bases, education, and other domains. However, a critical gap remains: **how do you know if your bot is actually giving accurate, grounded answers?**

Most RAG (Retrieval-Augmented Generation) systems are deployed with minimal evaluation. Builders rely on manual spot-checking or anecdotal feedback, leaving systemic issues — hallucinations, poor retrieval, irrelevant responses — undetected until users complain.

This project addresses that gap. It provides an **LLM-as-a-judge evaluation platform** that systematically tests an AI agent — your own RAG pipeline built in-app, or any external agent reachable via API — shows exactly *what* went wrong, proposes concrete fixes, and **verifies that applied fixes actually worked**.

## Design

### Core Idea

Rather than treating evaluation as a one-off check, Tribunal closes a full **diagnose → fix → verify loop**:

1. **Connect** the agent under test — build a RAG pipeline in-app (chunking, embedding, retrieval, LLM) or point a bot connector at any external agent (OpenAI, Claude, Gemini, DeepSeek, Glean, custom HTTP)
2. **Build a trustworthy test set** — generate persona-based questions from your documents (with source provenance) or upload your own; audit its quality and corpus coverage before trusting any verdict
3. **Run experiments** scoring every question against 25+ metrics, including refusal behavior on out-of-scope questions and retention across multi-turn conversations
4. **See what went wrong** — per-category breakdowns ("fails multi-hop and refusal questions"), retrieval-vs-generation attribution, confidence intervals instead of false precision
5. **Apply fixes** — guardrail/persona/phase prompt suggestions with ready-to-apply text, or let the Prompt Doctor draft a revised system prompt from your worst actual failures
6. **Verify** — re-runs are statistically compared per question; suggestions earn a "Fix verified" or "Made things worse" badge

### Architecture

```
                  +---------------------------+
                  |       React Web UI        |
                  |   guided flow + login     |
                  +-------------+-------------+
                                |
                  +-------------+-------------+
                  |   FastAPI REST (19 route  |
                  |   modules + auth/access   |
                  |   middleware + services)  |
                  +-------------+-------------+
                                |
       +---------------+-------------------+----------------+
       |               |                   |                |
+------+------+ +------+--------+ +--------+------+ +-------+--------+
|  Pipeline   | |  Evaluation   | |   Insights    | |   Database     |
| chunking    | | 25+ metrics   | | quality audit | | SQLite (local) |
| embedding   | | scoring+retry | | coverage      | | PostgreSQL     |
| retrieval   | | suggestions   | | breakdowns    | | users/projects |
| generation  | | prompt doctor | | CI gate       | | experiments    |
| connectors  | | skill arena   | | HTML report   | | test sets      |
| multi-LLM   | | testgen + KG  | | stats/CIs     | | suggestions    |
+------+------+ +---------------+ +---------------+ +----------------+
       |
+------+--------+
|  KG Worker    |  optional separate service — imports the SAME
|  build-kg     |  shared modules (no forked code); offloads
|  personas     |  memory-heavy KG builds and persona generation
+---------------+
```

### Suggestion Engine

The suggestion engine analyzes aggregate scores, per-question variance, and per-category gaps to produce **applyable** recommendations — prompt suggestions carry the actual guardrail text, not just advice:

| Signal | Diagnosis | Applied fix |
|--------|-----------|-------------|
| Low context recall | Retrieval misses relevant chunks | Increase `top_k` or switch to hybrid search |
| Low context precision | Too much irrelevant context retrieved | Decrease `top_k` or add reranking |
| Low faithfulness | Agent asserts claims the context doesn't support | **Grounding guardrail** appended to the system prompt |
| Low refusal accuracy | Agent fabricates answers to out-of-scope questions | **Refusal guardrail** appended to the system prompt |
| High noise sensitivity | Irrelevant retrieved passages leak into answers | **Context-filter guardrail** or reranking |
| Low answer relevancy | Responses drift from the question | **Persona + answer-first style rule**, or multi-step mode |
| Weak category (e.g. multi-hop trails the average by 0.2+) | Failure localized to a question type | The fix for *that* failure mode (e.g. **numbered reasoning phases**) |
| Both recall and precision low | Embedding model mismatch for the domain | Switch embedding model |
| High metric variance across questions | Inconsistent chunk quality | Try a different chunking strategy |

Beyond the rules, the **Prompt Doctor** sends your worst actual responses to an LLM that diagnoses the failure patterns and drafts a complete revised system prompt (persona + guardrails + phases), with each addition annotated by the failure it fixes — applyable for internal RAG configs, copyable into an external agent's own configuration.

Applying a suggestion clones the config, spawns a follow-up experiment, and — once it completes — computes a **statistical outcome** (paired bootstrap per question): the suggestion earns a `Fix verified`, `Made things worse`, `Mixed`, or `No significant change` badge. No more guessing whether a tweak helped.

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

### Agent Behavior
| Metric | What it measures |
|---|---|
| `refusal_accuracy` | On out-of-scope questions: did the agent decline (1.0), hedge (0.5), or fabricate (0.0)? Runs only on refusal-tagged questions |
| `conversation_retention` | On multi-turn questions: does the final answer honor facts established in earlier turns? Runs only on questions with setup turns |

### Retrieval Diagnostics (free, deterministic)
| Metric | What it measures |
|---|---|
| `retrieval_hit_rate` | Did retrieval fetch the chunk the gold answer lives in? Computed automatically from question provenance — no LLM cost |
| `retrieval_mrr` | Reciprocal rank of the first gold chunk in the retrieved list |

### SQL / Tabular Metrics
| Metric | What it measures |
|---|---|
| `datacompy_score` | SQL query result comparison |
| `sql_semantic_equivalence` | Semantic SQL query equivalence |

## Key Features

- **Verified-fix loop** — applied suggestions are statistically compared against the baseline per question (bootstrap confidence intervals) and badged `Fix verified` / `Made things worse` / `No significant change`; aggregate scores display their 95% CI so small test sets don't present noise as signal.
- **Test set transparency** — quality-audit any test set (verbatim leakage, ungrounded reference answers, non-self-contained or trivial questions), see corpus coverage with untested documents listed by name, and trace every generated question back to its source chunks.
- **Skill Arena** — test how well different AI models follow a SKILL.md-style instruction file: a judged (skill × model × question) matrix with a no-skill baseline, per-directive pass/fail verdicts, per-model *lift*, token/latency costs, step-level traces (optional Langfuse export), and one-click apply of the winning model as the project default.
- **Multi-turn conversation tests** — questions can carry setup turns; the runner plays them against the agent with history and the `conversation_retention` metric catches forgotten or contradicted context.
- **Multi-user accounts** — argon2-hashed logins with per-user project isolation, shareable project membership, and an admin role that sees everything; the first registered user becomes admin. Open mode (no accounts) keeps working for single-user self-hosting.
- **CI quality gate** — `GET .../experiments/{id}/gate?thresholds=faithfulness:0.7&strict=true` returns 412 on failure so pipelines can block deploys on agent quality.
- **Guided flow** — a Start page with two paths (test an external API agent vs build a RAG pipeline in-app), live per-step progress, and a "what's next" pointer; metric selection ships with Recommended / Free-only / Everything presets and plain-language descriptions.
- **Shareable reports** — one-click standalone HTML report per experiment: aggregates with confidence intervals, the per-category failure breakdown, and suggestions with verified outcomes.
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

# Frontend (separate terminal)
cd frontend && npm install && npm run dev  # dev server on :5173
```

### Authentication & user accounts

Tribunal has two auth layers that compose cleanly:

**User logins (recommended for teams).** Open the app and register — the **first account becomes the admin** and activates login enforcement for everyone. After that:

- Regular users only see projects they **own** or were **added to** (project owners add members by email from the Setup page).
- **Admins see and can manage every project**, plus a user-accounts panel (Workers page) to promote/demote roles.
- Set `SESSION_SECRET` in production (`openssl rand -hex 32`) or logins reset on every restart; set `SESSION_COOKIE_SECURE=true` behind HTTPS; set `ALLOW_REGISTRATION=false` to restrict signups to admin-provisioned accounts.
- Passwords are argon2id-hashed; logins are rate-limited per IP. There is no self-service password reset yet — an admin assists locked-out users.

**Machine token (CI/scripts).** Set `RAGAS_API_KEY` and pass `Authorization: Bearer <key>` — it acts as an admin identity, so quality-gate calls and automation keep working regardless of user logins. Before any user registers, the app runs in **open mode** exactly as previous versions did (optionally gated by this same key).

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
| `RAGAS_API_KEY` | — | Machine Bearer token (acts as admin); also gates open mode |
| `SESSION_SECRET` | — | **Set in production.** Signs login session cookies; unset = sessions reset on restart |
| `SESSION_TTL_SECONDS` | `1209600` | Session lifetime (14 days) |
| `SESSION_COOKIE_SECURE` | `false` | Mark session cookies Secure (set behind HTTPS) |
| `ALLOW_REGISTRATION` | `true` | `false` = only existing accounts can sign in |
| `LOGIN_RATE_LIMIT` | `5` | Login attempts per IP per minute |
| `DATABASE_URL` | — | PostgreSQL connection string; omit for SQLite |
| `KG_WORKER_URLS` | — | Comma-separated worker URLs for load-balanced KG builds |
| `KG_WORKER_URL` | — | Legacy single-worker URL (backward compat) |
| `KG_THREAD_MODE` | `false` | Run KG builds in a thread instead of subprocess |
| `ALLOW_PRIVATE_ENDPOINTS` | `false` | Allow requests to private IPs (disable SSRF protection) |
| `PORT` | `8000` | Server port |
| `CONTEXT_CHAR_BUDGET` | `100000` | Max characters of context sent to the LLM |
| `BOT_QUERY_TIMEOUT` | `120` | Seconds before a bot query times out |
| `KG_SUBPROCESS_TIMEOUT` | `86400` | Seconds before a KG build is killed (0 = no limit) |
| `KG_SUBPROCESS_MAX_RSS_MB` | `0` | Memory cap for KG build subprocesses, MB (0 = no limit; Linux) |
| `KG_COMPRESSION` | `true` | zlib-compress stored knowledge-graph JSON |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — | Optional. Export Skill Arena step traces to Langfuse (`pip install langfuse`) |
| `MAX_UPLOAD_SIZE` | `52428800` | Max document upload size in bytes (50 MB) |
| `MAX_BASELINE_ROWS` | `1000` | Max rows per baseline CSV upload |
| `MAX_UPLOAD_QA_ROWS` | `2000` | Max rows per test set CSV/JSON upload |
| `DEFAULT_EVAL_MODEL` | `gpt-4o-mini` | Default LLM for evaluation |
| `MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD` | `0.6` | Min reliability score to include a judge in consensus |
| `MULTI_LLM_JUDGE_TEMP_MIN` | `0.3` | Lowest judge temperature |
| `MULTI_LLM_JUDGE_TEMP_MAX` | `0.75` | Highest judge temperature |

## Project Structure

```
+-- app/                      # FastAPI application
|   +-- __init__.py           # App factory, auth/access middleware, lifespan
|   +-- models.py             # Pydantic request/response models
|   +-- services/             # Business logic shared across routes
|   |   +-- auth.py           # Password hashing, sessions, project access
|   |   +-- progress.py       # Lock-guarded run-state registry (SSE-safe)
|   |   +-- skill_trials.py   # Skill Arena matrix runner
|   |   +-- tracing.py        # Step tracing (+ optional Langfuse export)
|   +-- routes/               # 19 route modules
|       +-- auth.py           # Register/login/logout, admin user management
|       +-- projects.py       # Project CRUD, members, baselines, API config
|       +-- documents.py      # Document upload (PDF/TXT/DOCX)
|       +-- chunks.py         # Chunking configuration and preview
|       +-- embeddings.py     # Embedding configuration
|       +-- rag.py            # RAG config and single-query testing
|       +-- testsets.py       # Test set generation, KG endpoints, upload
|       +-- personas.py       # Persona CRUD and auto-generation
|       +-- experiments.py    # Experiment runner (SSE, conversations, retrieval diagnostics)
|       +-- analyze.py        # Suggestions, prompt doctor, apply + outcomes
|       +-- insights.py       # Quality audit, coverage, breakdown, CI gate, HTML report
|       +-- skills.py         # Skill Arena (skills, trials, apply-model)
|       +-- bot_configs.py    # External bot connector configs
|       +-- annotations.py    # Human annotation and evaluator accuracy
|       +-- reports.py        # Project-level reporting and trends
|       +-- custom_metrics.py # User-defined evaluation metrics
|       +-- multi_llm_judge.py# Multi-judge evaluation
|       +-- system.py         # Maintenance (vacuum, cache release)
|       +-- health.py         # Health check endpoint
+-- pipeline/                 # RAG engine
|   +-- chunking.py           # 6 chunking strategies + 2-step pipeline
|   +-- embedding.py          # OpenAI + SentenceTransformers + contextual prefix
|   +-- vectorstore.py        # ChromaDB integration
|   +-- bm25.py               # BM25 sparse search
|   +-- rag.py                # Retrieval + generation (dense/sparse/hybrid/reranker)
|   +-- llm.py                # Multi-provider LLM routing (OpenAI, Anthropic, Google)
|   +-- retry.py              # Backoff/retry for all LLM and HTTP calls
|   +-- bot_connectors/       # 7 connectors (system context + conversation history)
+-- evaluation/               # Metrics and analysis
|   +-- metrics/              # 26 metric modules (incl. refusal, retention, testgen)
|   +-- skills/               # Skill parsing + adherence judging
|   +-- scoring.py            # Metric orchestration with retries
|   +-- suggestions.py        # Rule engine + guardrail snippet library
|   +-- testset_quality.py    # Test set quality audit
|   +-- stats.py              # Bootstrap CIs, paired delta verdicts
+-- worker/                   # KG Worker service (separate FastAPI app)
|   +-- main.py, routes.py    # Imports the SAME shared modules above — no forked code
|   +-- Dockerfile            # Builds from repo root: docker build -f worker/Dockerfile .
+-- db/                       # Database layer
|   +-- init.py               # Schema, migrations, SQLite/PostgreSQL dual backend
+-- frontend/                 # React + TypeScript + Tailwind SPA
|   +-- src/
|       +-- api/              # Typed API client, one module per domain
|       +-- pages/            # Start, Login, Setup, Build, Test, Experiment, Analyze, Skills...
|       +-- components/       # Feature components + ui/ primitives
|       +-- hooks/            # useFetch, usePolling, useExperimentStream...
|       +-- contexts/         # Auth + project state
+-- tests/                    # pytest suite (450+ tests, mocked LLM layer)
+-- main.py                   # Uvicorn entrypoint
+-- Dockerfile
+-- docker-compose.yml
+-- requirements.txt
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
| Auth | argon2id password hashing, signed session cookies |
| Document parsing | pypdf (PDF), python-docx (DOCX) |
| Containerisation | Docker (multi-stage build), docker compose |
