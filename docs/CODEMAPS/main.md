# Tribunal RAG Evaluator -- Backend Codemap

**Last Updated:** 2026-06-13
**Entry Points:** main.py, app/__init__.py
**Primary Purpose:** REST API server, RAG pipeline, evaluation metrics, test generation, suggestions
**App version:** 0.4.1-alpha (Tribunal -- RAG Evaluator)

## Architecture

    main.py
      |-- langchain_community.chat_models.vertexai shim
      |-- load_dotenv()
      |-- from app import app  (calls create_app())
            |
            v
    app/__init__.py: create_app()
      |-- lifespan: init_db() + _monitor_worker_experiments task + client cleanup
      |-- _AuthMiddleware (open/user mode, per-project RE check, machine token)
      |-- CORSMiddleware (CORS_ORIGINS env var, default localhost:3000/5173)
      |-- 19 routers registered
      |-- SPA catch-all: /app/{path} -> frontend/dist/index.html
      |-- GET / -> RedirectResponse(/app/setup)

    Layers:
      app/routes/      (19 modules -- HTTP handlers)
      app/services/    (4 modules -- shared state/logic)
      evaluation/      (scoring engine, metrics, suggestions, testset quality)
      pipeline/        (chunking, embedding, vectorstore, bm25, rag, llm, connectors)
      db/init.py       (schema, dual-backend connection, migrations)
      config.py        (all env-driven constants)

## Entry Points

| File | Trigger |
|------|---------|
| main.py | uvicorn main:app --host 0.0.0.0 --port 8000 |
| app/__init__.py | imported by main.py; create_app() is the factory |

---

## app/__init__.py -- Factory and Middleware

**Lifespan** (startup/shutdown):
1. init_db() -- creates/migrates schema; fatal on failure (sys.exit(1))
2. asyncio.create_task(_monitor_worker_experiments) -- every 30s polls worker
   /experiment-progress/{eid} for delegated experiments; marks failed after 3
   consecutive unreachable calls; experiment_runs.release(eid) on completion
3. On shutdown: cancels monitor task; calls close_*_client() for openai,
   anthropic, gemini, embedding clients to avoid event-loop-closed warnings

**_AuthMiddleware** (Starlette BaseHTTPMiddleware):
- Exempt prefixes: /app/, /health, /api/auth/
- Open mode (no users): pass-through unless RAGAS_API_KEY set -> Bearer check
- User mode (>=1 registered user, lazily cached via _auth_active_cache):
  - resolve_request_user() -> session cookie (itsdangerous) or machine Bearer
  - _PROJECT_PATH_RE matches /api/projects/{id}/ -- project-scoped paths
    additionally call user_can_access_project() (owner/member/admin)
  - Attaches request.state.user
- 401 for unauthenticated, 403 for project scope violation

**SPA serving**: mounts /app/assets as StaticFiles; all other /app/* serve
frontend/dist/index.html; 503 with build instructions when dist not found.

---

## config.py

| Section | Key Variables |
|---------|--------------|
| Storage paths | DATABASE_URL, DATABASE_PATH, CHROMADB_PATH, BM25_PATH |
| Default eval models | DEFAULT_EVAL_MODEL (gpt-4o-mini), DEFAULT_EVAL_EMBEDDING, DEFAULT_EVAL_MAX_TOKENS |
| Connector defaults | CONNECTOR_DEFAULT_MODELS dict (openai/claude/deepseek/gemini), VALID_CONNECTOR_TYPES |
| Suggestion thresholds | SUGGESTION_HIGH_THRESHOLD (0.4), SUGGESTION_MEDIUM_THRESHOLD (0.7) |
| Timeouts | BOT_QUERY_TIMEOUT (120s), METRIC_SCORING_TIMEOUT (300s), TESTGEN_SUBPROCESS_TIMEOUT (7200s), KG_SUBPROCESS_TIMEOUT (86400s) |
| Upload limits | MAX_UPLOAD_SIZE (50MB), MAX_BASELINE_ROWS (1000), MAX_UPLOAD_QA_ROWS (2000) |
| LLM temps | TESTGEN_TOPIC_TEMPERATURE=0.0, TESTGEN_PERSONA_TEMPERATURE=0.7, TESTGEN_QUESTION_TEMPERATURE=0.8 |
| KG concurrency | MAX_CONCURRENT_KG_BUILDS (1), MAX_CONCURRENT_PERSONA_BUILDS (2) |
| Batch sizes | EMBEDDING_BATCH_SIZE (100), KG_BATCH_SIZE (50) |
| Auth | SESSION_SECRET, SESSION_TTL_SECONDS (14d), SESSION_COOKIE_SECURE, LOGIN_RATE_LIMIT (5/min) |
| Multi-LLM Judge | MULTI_LLM_JUDGE_DEFAULT_EVALUATORS (3), MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD (0.6), temp range 0.3-0.75 |
| Worker | KG_WORKER_URLS list, KG_WORKER_URL (first URL), KG_THREAD_MODE bool |
| Network | ALLOW_PRIVATE_ENDPOINTS bool (SSRF guard for private IPs) |
| Validation | VALID_CHUNK_METHODS, VALID_EMBEDDING_TYPES, VALID_SEARCH_TYPES, VALID_RESPONSE_MODES |
| RAG | CONTEXT_CHAR_BUDGET (100000 chars), MAX_CHUNKS_FOR_GENERATION |

---

## app/routes/ -- 19 Modules

| Module | One-line purpose |
|--------|-----------------|
| health.py | GET /health, GET /config/defaults, GET /workers/status, worker clear-build/clear-personas proxies |
| auth.py | Register/login/logout/me, admin user management, role updates; first user becomes admin |
| projects.py | Project CRUD; preferred_model field; project-member management |
| documents.py | File upload (txt/pdf/docx), list, delete, chunk preview |
| chunks.py | Chunk config CRUD, chunk generation, 2-step pipeline support |
| embeddings.py | Embedding config CRUD, embed chunks, dense/hybrid search endpoints |
| rag.py | RAG config CRUD, ad-hoc single-shot/multi-step query endpoint |
| testsets.py | Test set CRUD, KG build (worker delegation or local), progress polling, question editing |
| experiments.py | Experiment CRUD, SSE runner, compare/history/delta/export, model registry |
| analyze.py | Suggestion generate/retrieve/apply/batch-apply, Prompt Doctor (LLM revision) |
| insights.py | Quality audit, corpus coverage, per-category breakdown, CI gate, HTML report |
| bot_configs.py | Bot config CRUD, connection test; 7 connector types |
| annotations.py | Human feedback on results, evaluator accuracy sampling |
| reports.py | Per-bot aggregates, source-verification summary, cross-experiment trends |
| personas.py | Persona CRUD, async persona generation (subprocess or worker delegation) |
| custom_metrics.py | Custom metric CRUD; 6 types: integer_range, similarity, rubrics, instance_rubrics, criteria_judge, reference_judge |
| multi_llm_judge.py | Fetch judge evaluations, annotation sample, claim annotations, reliability stats |
| skills.py | Skill CRUD (SKILL.md-style docs), skill trial lifecycle, results, apply-model endpoint |
| system.py | POST /system/maintenance: WAL checkpoint, VACUUM, progress eviction, cache release, GC |


### experiments.py -- Core Evaluation Loop

Notable endpoints:

    POST   /api/projects/{p}/experiments                 create (RAG or bot path)
    POST   /api/projects/{p}/experiments/{id}/run        start SSE runner
    GET    /api/projects/{p}/experiments/{id}/progress   SSE stream
    GET    /api/projects/{p}/experiments/compare         2-5 exp alignment view
    GET    /api/projects/{p}/experiments/history         completed list + aggregates
    GET    /api/projects/{p}/experiments/{id}/results    per-question results
    DELETE /api/projects/{p}/experiments/{id}
    GET    /api/models                                   list provider models

Multi-turn conversation flow (_process_question):
- metadata.turns carries prior user messages (setup turns)
- Bot runs: iterates conversation_turns, sends each with accumulated chat_history,
  then sends the final question; _transcript injected into q_metadata
  so conversation_retention metric can see it

Retrieval diagnostics (internal RAG only, no LLM call):
- _retrieval_diagnostics() computes retrieval_hit_rate and retrieval_mrr
  against metadata.source_chunk_ids

Worker delegation (bot-connector experiments only):
- Tries each KG_WORKER_URLS with POST /run-experiment; on 202 sets
  experiment_runs.set_worker(eid, url); _reap_stale_experiments() skips these

SSE progress: {phase, current, total, question, error, completed_items,
               in_flight_details, scoring_metrics}

### analyze.py -- Suggestion Engine + Prompt Doctor

Endpoints:
    POST  .../suggestions/generate
    GET   .../suggestions
    PATCH .../suggestions/{s}           (implemented flag)
    POST  .../suggestions/{s}/apply     single apply + clone config + new exp
    POST  .../suggestions/apply-batch
    POST  .../prompt-doctor

Prompt Doctor: fetches worst 8 scored results, calls chat_completion with
_PROMPT_DOCTOR_TEMPLATE, parses diagnosis + additions + revised_system_prompt.

Outcome verification: lazily computed once applied_experiment_id completes;
calls paired_delta_verdict per metric; cached in suggestions.outcome_json.
Verdict: improved/regressed/mixed/inconclusive.

### insights.py -- Quality, Coverage, CI Gate, HTML Report

Endpoints:
    POST  .../test-sets/{ts}/quality-audit
    GET   .../test-sets/{ts}/coverage
    GET   .../experiments/{e}/breakdown
    GET   .../experiments/{e}/report
    GET   .../experiments/{e}/gate

CI gate: ?thresholds=faithfulness:0.7&strict=true -> HTTP 412 on failure.
HTML report: server-rendered; bootstrap_ci, breakdown, suggestions with outcome badges.

---

## app/services/


### auth.py
- argon2id password hashing (argon2-cffi _hasher)
- itsdangerous URLSafeTimedSerializer for session cookies
- CurrentUser frozen dataclass: id, email, name, role, is_admin property
- MACHINE_USER sentinel (id=None, role=admin) for RAGAS_API_KEY bearer
- resolve_request_user(conn, request) -- tries cookie then Bearer token
- user_can_access_project(conn, user, project_id) -- owner OR member OR admin
- login_throttled(ip) -- in-memory sliding window, 5 req/min, bounded to 10k IPs

### progress.py -- ProgressStore
- ProgressStore: RLock-protected dict registry for experiment run state
- Per-experiment state: progress dict, cancel event, asyncio task, worker URL
- set_progress / mutate_progress (apply fn under lock) / snapshot_progress (deep copy)
- is_alive(eid), delegated(), release(eid), evict_stale() (30-min TTL)
- experiment_runs = ProgressStore() module singleton
- skill_trial_runs = ProgressStore() in skill_trials.py (separate instance)

### skill_trials.py
- run_skill_trial(trial_id) -- asyncio background task
- _query_model dispatches to chat_completion (kind=llm) or bot connector (kind=bot)
- judge_adherence() per cell -> skill_adherence score + format_compliance
- aggregate_trial_matrix() -- model x variant summary with lift calculation

### tracing.py
- TraceRecorder: context-manager span() with wall time, status, attrs
- Optional Langfuse export; supports Langfuse v2 and v3 APIs

---

## pipeline/

### chunking.py -- 6 strategies
recursive, markdown, token, fixed_overlap, parent_child, semantic
2-step pipeline: chunk_text_pipeline(method, params, step2_method, step2_params)

### embedding.py
embed_texts_dispatch() / embed_query_dispatch() -- routes to OpenAI dense,
SentenceTransformers, or BM25. release_models() evicts cached ST instances.

### vectorstore.py -- ChromaDB
get_or_create_collection(), search(), add_documents().
ChromaDB calls wrapped in asyncio.to_thread() from rag.py (blocking API).

### bm25.py
build_bm25_index(), search_bm25(), persistent pickle indices in BM25_PATH.

### rag.py -- dense / sparse / hybrid RRF + reranker + multi-step
- single_shot_query -- retrieve -> truncate -> LLM
- multi_step_query -- up to max_steps: retrieve -> reason -> refine query
- Hybrid: parallel dense + sparse, RRF merge (alpha weight), optional reranker
- _truncate_contexts() -- drops lowest-scored contexts to fit CONTEXT_CHAR_BUDGET

### llm.py -- provider routing + gateway mode
- _LLM_GATEWAY_MODE: when OPENAI_BASE_URL set, all models route via OpenAI client
- Prefix detection: gpt-/o1/o3/o4 -> OpenAI; claude- -> Anthropic; gemini- -> Google
- Module-level singleton clients (lazy init, connection reuse)
- get_available_judge_models() returns all known models with availability bool

### retry.py -- with_backoff
with_backoff(operation, attempts=3, base_delay=2.0, max_delay=60.0, label):
- Retryable: HTTP 429/500/502/503/504 or exception name containing
  timeout/connect/network/transport
- Respects Retry-After header; exponential backoff with jitter

### bot_connectors/
BotConnector Protocol: query(question, *, system_context=None, history=None)
SystemContextUnsupported / ConversationUnsupported sentinel exceptions

| Connector | Notes |
|-----------|-------|
| openai_bot.py | OpenAI chat API; supports system_context + history |
| claude_bot.py | Anthropic; supports system_context + history |
| deepseek_bot.py | OpenAI-compatible endpoint; supports system_context + history |
| gemini_bot.py | Google GenAI; supports system_context + history |
| glean.py | Glean enterprise search REST; raises both unsupported exceptions |
| custom.py | Generic HTTP POST; raises both unsupported exceptions |
| csv_connector.py | Pre-loaded CSV answers; raises both unsupported exceptions |

---

## evaluation/

### scoring.py -- metric registry + evaluate_experiment_row

ALL_METRICS (26 entries):
  faithfulness, answer_relevancy, context_precision, context_recall,
  context_entities_recall, noise_sensitivity, factual_correctness,
  semantic_similarity, non_llm_string_similarity, bleu_score, rouge_score,
  chrf_score, exact_match, string_presence, summarization_score, aspect_critic,
  rubrics_score, answer_accuracy, context_relevance, instance_rubrics,
  response_groundedness, refusal_accuracy, conversation_retention,
  sql_semantic_equivalence, datacompy_score, multi_llm_judge

setup_scorers(metrics, custom_configs, rubrics) -> (builtin_scorers, custom_scorers, llm)
[] metrics -> no built-in metrics; multi_llm_judge excluded (separate execution path)

_SCORE_SIGNATURES -- 13 call patterns:
- metadata_refusal: refusal_accuracy, conversation_retention (conditional on metadata)
- metadata_sql: sql_semantic_equivalence (needs reference_sql)
- metadata_data: datacompy_score (needs reference_data)

evaluate_experiment_row() -- asyncio.gather(); each with with_backoff(attempts=2)
inside wait_for(METRIC_SCORING_TIMEOUT); errors always return None.

### metrics/ -- notable modules

| Module | Special notes |
|--------|--------------|
| refusal_accuracy.py | Only on expected_behavior=refusal; refused(1.0)/hedged(0.5)/fabricated(0.0) |
| conversation_retention.py | Only when metadata._transcript present; retained/partial/forgot |
| multi_llm_judge.py | N parallel evaluators at linearly-spaced temps; per-claim annotations |
| custom_metric.py | 4 scoring functions: integer_range, similarity, rubrics, instance_rubrics |
| testgen.py | generate_testset_from_chunks/with_personas, build_kg_standalone |
| sql_semantic_equivalence.py | Uses metadata.reference_sql + metadata.schema_contexts |
| datacompy_score.py | Uses metadata.reference_data (structured data comparison) |
| tool_call_accuracy.py | Exact-match tool call name + args |
| tool_call_f1.py | F1 over predicted vs expected tool call set |
| topic_adherence.py | Embedding similarity of response to expected topic |
| agent_goal_accuracy.py | Whether multi-step agent achieved the declared goal |

### skills/

parser.py: parse_skill(content) -> {name, summary, directives[]}
_extract_json_object() also used by prompt-doctor in analyze.py

adherence.py: judge_adherence(question, answer, directives, judge_model):
per-directive verdict; deterministic (format) vs semantic split;
returns {score, results[{directive, verdict, deterministic}]}

### suggestions.py

GUARDRAIL_SNIPPETS -- 7 system-prompt additions:
grounding, refusal, noise_filter, directness, phased_reasoning, persona, clarify_edge

generate_suggestions rules:
- context_recall < 0.7 -> top_k +5; context_precision < 0.7 -> top_k -2
- faithfulness < 0.7 -> grounding snippet; refusal_accuracy < 0.7 -> refusal snippet
- answer_relevancy < 0.7 -> response_mode=multi_step
- Category gap > 0.2 below overall average -> targeted snippet (_category_rules)

apply_config_change: system_prompt_append appends (does not replace);
relative deltas (+5/-2) for numeric fields; returns (updated_fields, changes)

### testset_quality.py / stats.py
audit_test_set() -- per-question quality flags + score
bootstrap_ci(values) -- 95% CI; paired_delta_verdict() -- per-metric verdict

---

## db/init.py -- Schema + Dual Backend

30+ tables:

| Table | Notable columns |
|-------|----------------|
| projects | judge_model_assignments_json, preferred_model, owner_id |
| users | email (unique), name, password_hash, role (admin/user) |
| project_members | project_id, user_id, role; UNIQUE(project_id, user_id) |
| chunk_configs | step2_method/step2_params_json; filter_params_json |
| chunks | parent_chunk_id; embedding_blob |
| embedding_configs | type: dense_openai / dense_sentence_transformers / bm25_sparse |
| rag_configs | search_type, sparse_config_id, alpha, reranker_model, reranker_top_k |
| test_questions | category, metadata_json (source_chunk_ids, turns, expected_behavior) |
| experiments | bot_config_id, baseline_experiment_id, retrieval_config_json snapshot |
| experiment_results | retrieved_contexts, metrics_json, metadata_json |
| suggestions | config_field, suggested_value, applied_experiment_id, outcome_json |
| multi_llm_evaluations | evaluator_index, verdict, claims_json, reasoning |
| evaluator_claim_annotations | human claim-level feedback; UNIQUE(evaluation_id, claim_index) |
| knowledge_graphs | kg_source, chunk_config_id; UNIQUE(project_id, kg_source) |
| custom_metrics | metric_type (6 types), refined_prompt, few_shot_examples_json |
| skills | content, parsed_directives_json; UNIQUE(project_id, name, version) |
| skill_trials | models_json, include_baseline |
| skill_trial_results | directive_results_json, trace_json, tokens_in/out, latency_ms |
| api_configs | per-project custom API endpoint; UNIQUE(project_id) |

Dual backend: _USE_PG = bool(DATABASE_URL); _PgConnection/_PgCursor wrappers
convert ? -> %s, auto-append RETURNING id, %% escapes literal %.
Migration: _add_column_if_missing() on every init_db(); ~25 incremental migrations.

Connection model:
- Main thread: single module-level _connection
- Background threads: threading.local() via get_thread_db()
- PG health-checked with SELECT 1, auto-reconnect on close
- NOW_SQL and json_extract_sql() provide backend-aware SQL fragments

---

## Key Flows

### 1. Startup

    uvicorn main:app
      |-- langchain_community shim injected
      |-- load_dotenv()
      |-- lifespan: init_db() -> _connection set
      |-- _monitor_worker_experiments task (30s poll)
      |-- 19 routers, SPA configured
      |-- ready

### 2. Experiment Run

    POST /api/projects/1/experiments/10/run
      |-- atomic UPDATE status to running
      |-- try worker delegation (bot exps only) -> set_worker or run local
      |-- asyncio.create_task(_run_background)
      |   |-- setup_scorers()
      |   |-- Semaphore(concurrency) limits parallel questions
      |   |-- for each question:
      |   |   |-- multi-turn: play setup turns, accumulate chat_history
      |   |   |-- RAG: single_shot_query or multi_step_query
      |   |   |-- evaluate_experiment_row() -> asyncio.gather
      |   |   |-- retrieval_diagnostics() for RAG (no LLM)
      |   |-- INSERT results, UPDATE status=completed
    GET .../progress (SSE) -> snapshot_progress every 2s, heartbeat every 15s

### 3. Suggestion Apply -> Verify

    POST .../suggestions/generate
      |-- generate_suggestions() -> DELETE old + INSERT new

    POST .../suggestions/42/apply
      |-- apply_config_change() -> INSERT cloned rag_config with change
      |-- INSERT experiment (pending, baseline_experiment_id=original)
      |-- UPDATE suggestion: implemented=TRUE, applied_experiment_id=new_eid

    GET .../suggestions (after new experiment completes)
      |-- _resolve_outcome() -> paired_delta_verdict per metric
      |-- verdict cached in suggestions.outcome_json

### 4. Skill Trial

    POST /api/projects/1/skill-trials
      |-- parse_skill() validates directives
      |-- run_skill_trial(trial_id) asyncio task
      |   |-- cells: (skill|baseline) x models x questions
      |   |-- each: query -> judge_adherence -> TraceRecorder -> INSERT results
      |-- aggregate_trial_matrix() -> lift = skill - baseline per model

---

## Key Patterns

### Shared Connection (get_db)
Main thread reuses _connection; background threads use threading.local.
No ORM, no connection pool library.

### Metric Registry (ALL_METRICS / _METRIC_MODULES)
Factory pattern: create_scorer() + async score(). _SCORE_SIGNATURES groups by
argument shape; _score_builtin builds partial(). multi_llm_judge in ALL_METRICS
for UI but NOT in _METRIC_MODULES (separate execution path).

### ProgressStore (experiment_runs / skill_trial_runs)
threading.RLock protects all state. mutate_progress applies fn under lock.
snapshot_progress returns deep copy for safe SSE serialization.
Two separate ProgressStore instances for experiments vs skill trials.

### Retry Pattern (with_backoff)
Centralized in pipeline/retry.py. Covers httpx, openai SDK, requests.
Metric scorers additionally wrapped in asyncio.wait_for(METRIC_SCORING_TIMEOUT).

### Middleware Auth Flow

    _AuthMiddleware.dispatch
      |-- exempt path? -> pass through
      |-- _auth_is_active? (lazy cache, flips True once)
      |    False -> optional RAGAS_API_KEY bearer check
      |    True  -> resolve_request_user (cookie OR machine bearer)
      |             None -> 401
      |    project path? -> user_can_access_project
      |             False -> 403
      |-- request.state.user = user -> call_next

---

## External Dependencies

Core: fastapi, uvicorn, pydantic, python-dotenv
Database: sqlite3 (bundled), psycopg2-binary (PostgreSQL/Neon)
RAG Pipeline: ragas, langchain-text-splitters, chromadb, bm25-pt
LLM: openai, anthropic, google-generativeai
Auth: argon2-cffi, itsdangerous
Utilities: httpx (async HTTP), pypdf, python-docx
Optional: langfuse (skill trial tracing, env-keyed)

## Related Areas
- Worker Service (docs/CODEMAPS/worker.md) -- KG builder + experiment runner offloading
- Frontend (docs/CODEMAPS/frontend.md) -- React SPA
- CLAUDE.md -- Quick reference
