# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

RAG Evaluator — an LLM-as-a-judge platform for testing and improving RAG chatbots. Configures RAG pipelines, generates synthetic test sets, runs evaluation experiments against 20+ metrics, and produces actionable suggestions.

## Commands

```bash
# Backend (main app)
pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY (required)
uvicorn main:app --host 0.0.0.0 --port 8000

# Worker (separate service, optional but recommended for production)
cd worker
pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY (required)
uvicorn main:app --host 0.0.0.0 --port 3000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev   # dev server on :5173
cd frontend && npm run build                # production build → frontend/dist/

# Docker (full stack with worker)
docker compose up --build

# Tests
pytest                          # all tests
pytest tests/unit/              # unit only
pytest tests/integration/       # integration only
pytest -k test_chunking_engine  # single test file
pytest --cov=app --cov=evaluation --cov=pipeline --cov-report=term-missing
```

## Architecture

### Main Application
```
main.py → loads .env, imports app from app/__init__.py
app/__init__.py → create_app() factory: lifespan (init_db, cleanup), CORS, router registration, SPA catch-all
app/routes/ → 14 route modules, each exports `router = APIRouter(prefix=..., tags=[...])`
app/models.py → all Pydantic request/response models
config.py → centralized env-var-driven configuration (paths, model defaults, thresholds, limits)
db/init.py → SQLite schema, migrations, all DB query functions (single module)
pipeline/ → RAG engine: chunking.py, embedding.py, vectorstore.py (ChromaDB), bm25.py, rag.py, llm.py
evaluation/ → metrics/, scoring.py (orchestration), suggestions.py (rule engine), testgen.py (synthetic QA)
frontend/ → React 18 + TypeScript + Vite + Tailwind SPA
```

### Worker Service (Knowledge Graph Builder)
```
worker/main.py → FastAPI app for KG builds; lifespan initializes worker DB
worker/routes.py → 5 endpoints: POST /build-kg (async task), GET /progress/{project_id}, GET /health, DELETE /kg/{project_id}, POST /clear-build/{project_id}
worker/config.py → env-var-driven config: timeouts, paths, concurrency (MAX_CONCURRENT_KG_BUILDS=1 default), batch sizes
worker/db/init.py → Worker-specific DB (595 lines): knowledge graph tables, entity/edge schemas, build progress tracking
worker/evaluation/metrics/testgen.py → Test generation (2630 lines): build_kg_standalone(), build_kg_standalone_from_documents(), progress tracking, KG metadata storage
```

The worker offloads memory-intensive knowledge graph (KG) construction from the main app. It operates independently as a separate FastAPI service that the main app communicates with via HTTP. Progress is polled via GET /progress and results are stored in the shared database.

### Key data flow

1. **App startup**: `main.py` → `app/__init__.py:lifespan()` → `db.init.init_db()` creates/migrates SQLite at `data/ragas.db` (WAL mode)
2. **Experiment execution**: `app/routes/experiments.py` streams progress via SSE → calls `evaluation/scoring.py` which dynamically imports metric functions from `evaluation/metrics/`
3. **SPA serving**: Built frontend in `frontend/dist/` is served by FastAPI static files mount; all `/app/*` routes fall through to `index.html`
4. **Worker KG Build**: Main app POSTs `/build-kg` request to worker (if `KG_WORKER_URL` env var set) → worker spawns thread for KG construction → main app polls `/progress/{project_id}` via SSE → results written to shared database (PostgreSQL or SQLite)

### Key patterns

- **Database**: Single shared `sqlite3.Connection` in `db/init.py` (module-level `_connection`). All DB access is through functions in that module — no ORM. Worker uses the same database schema and connection model in `worker/db/init.py`.
- **Metrics**: Each file in `evaluation/metrics/` exports a single async function. Wired into `scoring.py` which maintains `ALL_METRICS` list and a dispatch map. Worker's `worker/evaluation/metrics/testgen.py` implements KG building functions.
- **LLM routing**: `pipeline/llm.py` handles OpenAI, Anthropic, Google GenAI. Bot connectors (OpenAI, Claude, DeepSeek, Gemini, Glean, custom HTTP, CSV) configured via `app/routes/bot_configs.py`.
- **Config**: All tuneable values live in `config.py`, reading from env vars with defaults. Validation sets (`VALID_CHUNK_METHODS`, `VALID_SEARCH_TYPES`, etc.) are also here. Worker has its own `worker/config.py` with KG-specific settings.
- **SSE streaming**: Used for long-running experiment execution in `app/routes/experiments.py`. Worker progress is also tracked via polling.
- **Worker threading**: Worker uses daemon threads in `worker/routes.py` to handle KG builds. Thread-safe lock (`_kg_lock`) manages concurrent builds with `MAX_CONCURRENT_KG_BUILDS` limit.

## Database

- **Local / self-hosted**: SQLite at `data/ragas.db` (created on first run via `db/init.py`), WAL mode enabled
- **Server / production**: PostgreSQL via `DATABASE_URL` env var (e.g. Neon) — auto-detected in `db/init.py`
- Schema and all migrations in `db/init.py` — no separate migration files
- Query functions also live in `db/init.py` (single-module data layer)

## Deployment Modes

- **Self-host**: `docker compose up --build` — main app serves on `PORT` (default 8000), SQLite storage in `./data/`. To include worker: add worker service to docker-compose.yml
- **Server (Northflank + Neon)**: Dockerfile exposes port 3000, `PORT` set by platform, `DATABASE_URL` points to Neon PostgreSQL. Deploy worker separately and set `KG_WORKER_URL` env var
- **Local dev**: `uvicorn main:app --reload` + `cd worker && uvicorn main:app --port 3000` (in separate terminal) + `cd frontend && npm run dev` (Vite on :5173)
- **Worker only**: `cd worker && docker build -f Dockerfile -t kg-worker . && docker run -e PORT=3000 -e DATABASE_URL=... kg-worker` (runs knowledge graph builder as independent service)

## Environment Variables

### Main App
- `OPENAI_API_KEY` (required) — OpenAI API access
- `RAGAS_API_KEY` (optional but recommended) — Bearer token auth; without it all endpoints are public
- `DATABASE_URL` (optional) — PostgreSQL connection string; defaults to SQLite if unset
- `PORT` (optional) — server port; defaults to 3000 in Dockerfile, 8000 in docker-compose
- `CORS_ORIGINS` (optional) — comma-separated allowed origins (default: `localhost:3000,localhost:5173`)
- `KG_WORKER_URL` (optional) — worker URL for offloading KG builds (e.g. `http://kg-worker:3000`). If unset, KG builds run in-process
- `KG_WORKER_URLS` (optional) — comma-separated worker URLs for load balancing; tried in order
- See `.env.example` for full list: storage paths, default models, timeouts, batch sizes, suggestion thresholds

### Worker Service
- `OPENAI_API_KEY` (required) — OpenAI API access
- `DATABASE_URL` (optional) — PostgreSQL connection string (must match main app's database); defaults to SQLite if unset
- `PORT` (optional) — worker port; defaults to 3000
- `CORS_ORIGINS` (optional) — comma-separated allowed origins
- `MAX_CONCURRENT_KG_BUILDS` (optional) — max concurrent KG builds (default: 1). Set higher for multi-worker deployments
- `KG_SUBPROCESS_TIMEOUT` (optional) — timeout in seconds for KG builds (default: 86400 = 24h). Set to 0 to disable
- See `worker/.env.example` for full list

## Testing

- pytest with `asyncio_mode = auto` in `pytest.ini`
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`
- `tests/conftest.py` provides: `tmp_db` (fresh SQLite), `sample_project`, `sample_texts`, `sample_chunks`, `mock_openai_embeddings`, `mock_chat_completion`
- Unit tests cover pipeline components; integration tests hit the FastAPI app

## Worker API Routes

The worker service exposes 5 endpoints for knowledge graph construction:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check (always returns `{"status": "ok"}`) |
| `/build-kg` | POST | Start a KG build asynchronously (request: `BuildKGRequest`; response: 202 Accepted) |
| `/progress/{project_id}` | GET | Poll build progress (query param `kg_source`: "chunks" or "documents") |
| `/kg/{project_id}` | DELETE | Delete a KG (query param `kg_source`) |
| `/clear-build/{project_id}` | POST | Clear stale build lock (query param `kg_source`) |

The worker maintains thread-safe state using `_kg_lock` and `_active_builds` to prevent concurrent builds of the same project/source. The build itself runs in a daemon thread and updates progress in the shared database, which the main app polls via `/progress`.

### Worker Integration (Main App)

The main app (`app/routes/testsets.py`) handles offloading:

1. **Build Request**: When `KG_WORKER_URLS` is configured, main app POSTs `/build-kg` to worker (tries multiple workers in order)
2. **Conflict Detection**: If build already in progress → 409 response → main app raises HTTPException
3. **Capacity Handling**: If worker at capacity (503) → tries next worker in list
4. **Progress Polling**: Main app GET `/progress/{project_id}` from known worker or tries all workers
5. **Fallback**: If no workers configured or all unreachable, KG builds run in-process using threads (when `KG_THREAD_MODE=true`) or subprocesses

Config options:
- `KG_WORKER_URLS` (comma-separated list) — primary mechanism; tried in order
- `KG_WORKER_URL` (single URL) — legacy backward compatibility
- `KG_THREAD_MODE` (bool) — use threading instead of subprocess for in-process builds

## Conventions

- Python: PEP 8, type annotations on function signatures
- Frontend: TypeScript strict, Tailwind for styling
- New route modules: define `router = APIRouter(prefix=..., tags=[...])`, register in `app/__init__.py`
- New metrics: add async function in `evaluation/metrics/`, import in `scoring.py`, add to `ALL_METRICS`
- Worker routes: defined in `worker/routes.py`, each endpoint uses async handlers; DB state is managed by worker's own `worker/db/init.py`

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

## Preferred Runners
- use python3 instead of python, when running python files