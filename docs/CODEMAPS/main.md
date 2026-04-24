# Main Application Codemap

**Last Updated:** 2026-04-24  
**Entry Points:** `main.py`, `app/__init__.py`  
**Primary Purpose:** REST API server, RAG pipeline, evaluation metrics, test generation, suggestions

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Main Application (FastAPI)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│ main.py ──┐                                                       │
│           └─→ app/__init__.py:create_app()                       │
│               ├─ Lifespan: init_db(), cleanup                    │
│               ├─ CORS middleware                                 │
│               ├─ Register 14 routers from app/routes/            │
│               └─ SPA catch-all (frontend/dist/index.html)        │
│                                                                   │
│ app/models.py                                                    │
│ └─ Pydantic request/response types (all API contracts)          │
│                                                                   │
│ config.py                                                        │
│ └─ Env-driven configuration (paths, models, timeouts)           │
│                                                                   │
│ db/init.py (all data access)                                    │
│ ├─ Connection: sqlite3 (local) or psycopg2 (PostgreSQL)        │
│ ├─ Schema: 20+ tables (projects, chunks, configs, experiments)  │
│ └─ Query functions: create_*, get_*, update_*, delete_*         │
│                                                                   │
│ pipeline/ (RAG engine)                                           │
│ ├─ chunking.py (6 strategies)                                   │
│ ├─ embedding.py (OpenAI, SentenceTransformers, BM25)           │
│ ├─ vectorstore.py (ChromaDB for dense search)                  │
│ ├─ bm25.py (keyword-based sparse search)                       │
│ ├─ rag.py (single-shot and multi-step retrieval)               │
│ └─ llm.py (OpenAI, Anthropic, Google GenAI routing)            │
│                                                                   │
│ evaluation/ (Metrics & suggestions)                              │
│ ├─ metrics/ (20+ metric files)                                  │
│ ├─ scoring.py (orchestration, dynamic loading)                 │
│ ├─ suggestions.py (rule engine)                                │
│ └─ testgen.py (synthetic QA, personas)                         │
│                                                                   │
│ app/routes/ (14 route modules)                                  │
│ ├─ projects.py (CRUD, workspace management)                    │
│ ├─ documents.py (upload, chunking preview)                     │
│ ├─ chunk_configs.py (strategy, 2-step pipeline)                │
│ ├─ embedding_configs.py (model selection)                      │
│ ├─ rag_configs.py (bundle: chunking + embedding + LLM)         │
│ ├─ testsets.py (test generation, KG builds, worker delegation) │
│ ├─ experiments.py (run evaluation, stream progress via SSE)     │
│ ├─ results.py (per-question metrics, contexts)                 │
│ ├─ suggestions.py (generate, apply)                            │
│ ├─ bot_configs.py (7 connector types)                          │
│ ├─ custom_metrics.py (project-specific metric definitions)     │
│ ├─ annotations.py (human feedback, evaluator accuracy)         │
│ ├─ baselines.py (external reference Q&A)                       │
│ ├─ health.py (liveness, config defaults)                       │
│ └─ judge.py (multi-LLM evaluation, agreement tracking)         │
│                                                                   │
│ frontend/ (React SPA)                                            │
│ └─ Mounted as static files; SPA routes fall through to HTML     │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
              ▼           ▼           ▼
         SQLite       PostgreSQL   Worker
       (local)      (production)   Service
```

## Key Modules

### main.py (Single Entry Point)
- Loads `.env` via `dotenv`
- Imports app factory from `app/__init__.py`
- Exposes `app` for `uvicorn main:app`

### app/__init__.py (Factory)
- `create_app()` — FastAPI factory function
  - **Lifespan**: `db.init.init_db()` on startup
  - **CORS**: Configurable via `CORS_ORIGINS` env var
  - **Routers**: Registers 14 routers with prefixes
  - **SPA Catch-All**: `GET /app/*` → `frontend/dist/index.html`
- Serves frontend at `/` (static mount)

### config.py (132 lines)
Central env-driven configuration:

| Section | Variables |
|---------|-----------|
| **Storage** | `DATABASE_URL`, `DATABASE_PATH`, `CHROMADB_PATH`, `BM25_PATH` |
| **LLM Models** | `DEFAULT_EVAL_MODEL`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` |
| **Timeouts** | `BOT_QUERY_TIMEOUT`, `TESTGEN_SUBPROCESS_TIMEOUT`, `KG_SUBPROCESS_TIMEOUT` |
| **Limits** | `MAX_UPLOAD_SIZE`, `MAX_BASELINE_ROWS`, `MAX_UPLOAD_QA_ROWS` |
| **Worker** | `KG_WORKER_URLS`, `KG_WORKER_URL`, `KG_THREAD_MODE` |
| **Multi-LLM Judge** | `MULTI_LLM_JUDGE_DEFAULT_EVALUATORS`, `MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD` |
| **Validation Sets** | `VALID_CHUNK_METHODS`, `VALID_SEARCH_TYPES`, `VALID_RESPONSE_MODES` |

### db/init.py (All Data Access)
Module-level connection management + schema + query functions:

**Core Tables** (20+):
- `projects` — Workspaces
- `documents` — Uploaded files
- `chunks` — Split text segments
- `chunk_configs` — Chunking strategies (6 types)
- `embeddings` — Vector indices (dense, sparse)
- `embedding_configs` — Embedding model selection
- `rag_configs` — Pipeline bundles (chunking + embedding + LLM)
- `test_sets` — Generated test questions
- `test_questions` — Individual Q&A pairs with personas
- `experiments` — Evaluation runs
- `experiment_results` — Per-question scores
- `custom_metrics` — Project-specific metric definitions
- `annotations` — Human feedback on results
- `suggestions` — Generated recommendations
- `baselines` — External reference Q&A

**Query Functions**:
- `get_db()` (119 god node edges) — Connection factory
- `create_project()`, `get_project()`, `list_projects()`
- `upsert_chunks()`, `get_chunks_by_config()`
- `create_experiment()`, `get_experiment()`, `list_experiments()`
- `upsert_experiment_result()`, `get_experiment_results()`
- `create_annotation()`, `get_evaluator_accuracy()`

### app/models.py
Pydantic models for all API contracts:
- `ProjectCreate`, `ProjectUpdate`, `ProjectResponse`
- `ChunkConfigCreate`, `EmbeddingConfigCreate`, `RAGConfigCreate`
- `TestGenRequest`, `TestSetCreate`, `QuestionAnnotation`
- `ExperimentRequest`, `ExperimentResponse`
- `BotConfigCreate`, `BotConnectorType`
- `CustomMetricConfig` (4 types: integer_range, similarity, rubrics, instance_rubrics)
- etc.

### pipeline/ (RAG Engine)

#### chunking.py (6 Strategies)
- **recursive** — Recursive character splitting with overlap
- **markdown** — Split by headers, preserve structure
- **token** — Split by token count
- **fixed_overlap** — Fixed size with overlap
- **parent_child** — Hierarchical chunking (parent = larger context)
- **semantic** — Split by semantic boundaries (experimental)

**Key Function**: `chunk_text()` (39 god node edges)
- Parameters: strategy, chunk_size, overlap
- Returns: List of chunks with metadata
- Supports 2-step pipeline (e.g., markdown then recursive)

#### embedding.py
- `_embed_openai()` — OpenAI dense embeddings
- `_embed_sentence_transformers()` — Local open-source models
- `embed_texts_dispatch()` — Choose backend based on config
- Batching with `EMBEDDING_BATCH_SIZE`

#### vectorstore.py (ChromaDB)
- `get_or_create_collection()` — Lazy-load collection
- `search()` — Dense vector search
- `add_documents()` — Store embeddings

#### bm25.py (Sparse Search)
- `build_bm25_index()` — Build index from chunks
- `search()` — Keyword ranking
- Persistent indices in `BM25_PATH`

#### rag.py (Retrieval)
- `single_shot_query()` — 1-turn: retrieve, generate
- `multi_step_query()` — Iterative: retrieve → reason → refine (up to 10 steps)
- Hybrid search: dense + sparse with RRF
- Context budget: truncate if exceeds `CONTEXT_CHAR_BUDGET`

#### llm.py (LLM Routing)
- `chat_completion()` (21 god node edges) — Unified LLM interface
- Supports: OpenAI, Anthropic, Google GenAI
- Model selection via config
- LLM gateway support (custom OpenAI-compatible endpoints)
- Rate limiting, retries, timeout handling

### evaluation/ (Metrics & Suggestions)

#### metrics/ (20+ Metric Files)
Each file exports a single async function:
- `faithfulness()` — Response alignment with context
- `answer_relevancy()` — Answer pertinence to question
- `context_precision()`, `context_recall()` — Retrieval quality
- `exact_match()`, `bleu_score()`, `rouge_score()` — String metrics
- `semantic_similarity()` — Embedding cosine similarity
- `aspect_critic()`, `rubrics_score()` — LLM-as-judge
- `multi_llm_judge()` — Multi-model evaluation with agreement tracking
- `custom_*()` — Dynamic custom metrics

**Dynamic Loading**: `scoring.py` imports at runtime based on experiment config

#### scoring.py (Orchestration)
- `score_experiment()` — Run all configured metrics
- `score_question()` — Score a single question
- Parallel execution where possible
- Timeout handling per metric
- Error recovery (skip metric on timeout)
- `ALL_METRICS` list (manually maintained dispatch map)

#### suggestions.py (Rule Engine)
Analyzes metrics to produce actionable recommendations:
- Low context_recall → increase `top_k`
- Low context_precision → decrease `top_k`
- Low faithfulness → improve system prompt
- High variance → try different chunking strategy
- etc.

**Output**: List of `Suggestion` objects with target config field

#### testgen.py (Synthetic QA)
- `generate_testset_from_chunks()` — Random Q&A from chunks
- `generate_testset_with_personas()` — Persona-based generation
- `build_kg_standalone()` — Knowledge graph from chunks
- `build_kg_standalone_from_documents()` — KG from raw documents
- Progress tracking (stored in DB)
- Shared with worker service

### app/routes/ (14 Modules)

#### projects.py
```python
POST   /api/projects              # Create workspace
GET    /api/projects              # List all
GET    /api/projects/{id}         # Get one
DELETE /api/projects/{id}         # Delete
```

#### documents.py
```python
POST   /api/projects/{p}/documents         # Upload file
GET    /api/projects/{p}/documents         # List
DELETE /api/projects/{p}/documents/{id}    # Delete
POST   /api/projects/{p}/documents/{id}/preview-chunks  # Preview
```

#### chunk_configs.py
```python
POST   /api/projects/{p}/chunk-configs
GET    /api/projects/{p}/chunk-configs
PUT    /api/projects/{p}/chunk-configs/{id}
DELETE /api/projects/{p}/chunk-configs/{id}
```

#### testsets.py (Key for Worker Integration)
```python
POST   /api/projects/{p}/testsets                   # Create testset
GET    /api/projects/{p}/testsets                   # List
POST   /api/projects/{p}/testsets/{id}/build-kg     # Start KG build
GET    /api/projects/{p}/testsets/{id}/kg-progress  # Poll progress
DELETE /api/projects/{p}/testsets/{id}/kg           # Delete KG
GET    /api/projects/{p}/testsets/{id}/questions    # List questions
```

**Worker Delegation Logic** (in testsets.py):
1. Check if `KG_WORKER_URLS` set
2. Try each worker with POST `/build-kg`
3. Handle 409 (already building), 503 (busy)
4. Poll via GET `/progress/{project_id}`
5. Fallback to in-process if no workers

#### experiments.py (Core Evaluation Loop)
```python
POST   /api/projects/{p}/experiments                  # Start run
GET    /api/projects/{p}/experiments                  # List
GET    /api/projects/{p}/experiments/{id}             # Get one
GET    /api/projects/{p}/experiments/{id}/results     # Results
GET    /api/projects/{p}/experiments/{id}/progress    # SSE stream
DELETE /api/projects/{p}/experiments/{id}             # Cancel
```

**Progress Streaming**: Server-Sent Events (SSE)
- Client: `GET /progress` with EventSource
- Server: Sends updates every 2s
- Format: `data: {"stage": "scoring", "metric": "faithfulness", "progress": 0.45}`

#### bot_configs.py (7 Connector Types)
```python
POST   /api/projects/{p}/bot-configs
GET    /api/projects/{p}/bot-configs
PUT    /api/projects/{p}/bot-configs/{id}
DELETE /api/projects/{p}/bot-configs/{id}
POST   /api/projects/{p}/bot-configs/{id}/test    # Verify connection
```

**Supported Types**:
1. **openai** — ChatGPT-like via OpenAI API
2. **claude** — Claude via Anthropic API
3. **deepseek** — DeepSeek via API
4. **gemini** — Google Gemini via API
5. **glean** — Glean enterprise search
6. **custom** — Custom HTTP endpoint
7. **csv** — Upload pre-collected Q&A

#### custom_metrics.py
```python
POST   /api/projects/{p}/custom-metrics
GET    /api/projects/{p}/custom-metrics
PUT    /api/projects/{p}/custom-metrics/{id}
DELETE /api/projects/{p}/custom-metrics/{id}
```

**Types** (4):
- `integer_range` — LLM rates on scale (1-5)
- `similarity` — Compare answer to reference
- `rubrics` — User-defined rubric descriptions
- `instance_rubrics` — Per-question rubrics

#### judge.py (Multi-LLM Evaluation)
```python
GET    /api/projects/{p}/experiments/{e}/judge-evaluations
GET    /api/projects/{p}/experiments/{e}/judge-annotation-sample
GET    /api/projects/{p}/experiments/{e}/judge-reliability
POST   /api/projects/{p}/experiments/{e}/results/{r}/judge-evaluations/{ev}/claims
```

**Multi-Judge Agreement**:
- Run same metric on N judges (default: 3)
- Compute inter-judge agreement
- Flag low-confidence results
- Return individual verdicts + confidence score

#### annotations.py (Human Feedback)
```python
POST   /api/projects/{p}/experiments/{e}/annotations
GET    /api/projects/{p}/experiments/{e}/evaluator-accuracy
```

**Evaluator Accuracy**:
- Sample 20% of results (deterministic seed)
- Humans rate: accurate, partially accurate, inaccurate
- Compute agreement with automated metrics

#### suggestions.py
```python
GET    /api/projects/{p}/experiments/{e}/suggestions
POST   /api/projects/{p}/experiments/{e}/suggestions/{s}/apply
POST   /api/projects/{p}/suggestions/apply-batch
```

#### health.py
```python
GET /health                # Liveness
GET /api/config/defaults   # LLM models, batch sizes
GET /api/config/connectors # Available bot types
```

## Data Flow Examples

### 1. Create & Run Experiment

```
Frontend: POST /api/projects/1/experiments
├─ Request: {rag_config_id, testset_id, metrics: ["faithfulness", "..."], bot_config_id}
│
Main App: Create experiment row + stream progress via SSE
├─ Load testset questions from DB
├─ For each question:
│  ├─ Call bot or RAG pipeline
│  ├─ Get answer + context + citations
│  ├─ Score with all metrics (parallel where possible)
│  └─ Store result row
├─ Emit SSE event: {stage, metric, progress}
└─ Return completed experiment

Frontend: Receive SSE events
├─ Update progress bar
├─ When complete: fetch /results
└─ Display per-question metrics + aggregates
```

### 2. Build Knowledge Graph (With Worker)

```
Frontend: POST /api/projects/1/testsets/5/build-kg
├─ Request: {chunk_config_id, overlap_max_nodes: 500}
│
Main App: POST {worker_url}/build-kg
├─ Response: 202 Accepted {status: "building", project_id: 1, kg_source: "chunks"}
│
Frontend: Poll GET /api/projects/1/testsets/5/kg-progress
├─ Main App: GET {worker_url}/progress/1?kg_source=chunks
├─ Worker: Check _active_builds and return DB progress
│
Background (Worker):
├─ Thread: fetch chunks, extract entities/edges, save to DB
├─ Update kg_metadata, kg_build_progress tables
│
Frontend: Receive {active: true, stage: "building_knowledge_graph", percentage: 35}
├─ Display progress
└─ Poll again every 2s until {active: false, status: "completed"}
```

### 3. Apply Suggestion

```
Frontend: POST /api/projects/1/experiments/10/suggestions/2/apply
├─ Request: {suggestion_id: 2}
│
Main App:
├─ Fetch suggestion: {target_field: "top_k", new_value: 10}
├─ Fetch original RAG config
├─ Create new config with top_k=10
├─ Create new experiment with new config
└─ Return new experiment ID

Frontend: Redirect to experiment comparison view
└─ Compare metrics: old config vs new config
```

## External Dependencies

**Core**:
- `fastapi` — Web framework
- `uvicorn` — ASGI server
- `pydantic` — Request validation
- `python-dotenv` — Env var loading

**Database**:
- `sqlite3` — Bundled (dev/self-host)
- `psycopg2-binary` — PostgreSQL (production)

**RAG Pipeline**:
- `ragas` — Metrics, KG extraction, testgen
- `langchain-text-splitters` — Chunking strategies
- `chromadb` — Vector search
- `bm25-pt` — Sparse ranking

**LLM**:
- `openai` — OpenAI API
- `anthropic` — Claude API
- `google-generativeai` — Gemini API

**Utilities**:
- `httpx` — Async HTTP (worker delegation, bot calls)
- `pypdf` — PDF parsing
- `python-docx` — DOCX parsing

## Related Areas

- [Worker Service](./worker.md) — KG builder offloading
- [Frontend](./frontend.md) — React SPA
- [CLAUDE.md](../../CLAUDE.md) — Quick reference
