# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Tribunal (RAG Evaluator) — an LLM-as-a-judge platform for testing and improving AI agents: internal RAG pipelines built in-app or external agents called via API (bot connectors). Generates/audits test sets, runs experiments against 25+ metrics (incl. refusal behavior, multi-turn retention, deterministic retrieval diagnostics), produces applyable prompt/config suggestions, and statistically verifies applied fixes. Has multi-user auth (first registered user = admin) plus the Skill Arena for cross-model skill-file testing.

## Commands

```bash
# Backend
pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY (required)
uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev   # dev server on :5173
cd frontend && npm run build                # production build → frontend/dist/

# Docker (full stack)
docker compose up --build

# Tests
pytest                          # all tests
pytest tests/unit/              # unit only
pytest tests/integration/       # integration only
pytest -k test_chunking_engine  # single test file
pytest --cov=app --cov=evaluation --cov=pipeline --cov-report=term-missing
```

## Architecture

```
main.py → loads .env, imports app from app/__init__.py
app/__init__.py → create_app() factory: lifespan (init_db, worker monitor), _AuthMiddleware
                  (sessions + per-project access; open mode until a user registers),
                  CORS, router registration, SPA catch-all
app/routes/ → 19 route modules, each exports `router = APIRouter(prefix=..., tags=[...])`
              (incl. auth.py, insights.py, skills.py, system.py)
app/services/ → shared business logic: auth.py (argon2 + session cookies + access checks),
                progress.py (lock-guarded run-state, used by SSE), skill_trials.py, tracing.py
app/models.py → all Pydantic request/response models
config.py → centralized env-var-driven configuration (paths, model defaults, thresholds, limits)
db/init.py → schema, migrations, SQLite/PostgreSQL dual backend (single module, no ORM)
pipeline/ → RAG engine: chunking.py, embedding.py, vectorstore.py (ChromaDB), bm25.py, rag.py,
            llm.py (multi-provider routing), retry.py (backoff for ALL LLM/HTTP calls),
            bot_connectors/ (7 connectors; all accept system_context + history kwargs)
evaluation/ → metrics/ (26 modules), skills/ (skill parsing + adherence), scoring.py
              (orchestration + retries), suggestions.py (rule engine + guardrail snippets),
              testset_quality.py (audit), stats.py (bootstrap CIs, paired verdicts)
worker/ → optional KG worker service; imports the SAME shared modules (no forked copies);
          Docker build context is the REPO ROOT: docker build -f worker/Dockerfile .
frontend/ → React 18 + TS + Vite + Tailwind SPA: src/api/ (typed client per domain),
            src/hooks/ (useFetch, usePolling, useExperimentStream), src/contexts/ (Auth, Project)
```

### Key data flow

1. **App startup**: `main.py` → `app/__init__.py:lifespan()` → `db.init.init_db()` creates/migrates SQLite at `data/ragas.db` (WAL mode)
2. **Experiment execution**: `app/routes/experiments.py` streams progress via SSE → calls `evaluation/scoring.py` which dynamically imports metric functions from `evaluation/metrics/`
3. **SPA serving**: Built frontend in `frontend/dist/` is served by FastAPI static files mount; all `/app/*` routes fall through to `index.html`

### Key patterns

- **Database**: Single shared `sqlite3.Connection` in `db/init.py` (module-level `_connection`). All DB access is through functions in that module — no ORM.
- **Metrics**: Each file in `evaluation/metrics/` exports a single async function. Wired into `scoring.py` which maintains `ALL_METRICS` list and a dispatch map.
- **LLM routing**: `pipeline/llm.py` handles OpenAI, Anthropic, Google GenAI. Bot connectors (OpenAI, Claude, DeepSeek, Gemini, Glean, custom HTTP, CSV) configured via `app/routes/bot_configs.py`.
- **Config**: All tuneable values live in `config.py`, reading from env vars with defaults. Validation sets (`VALID_CHUNK_METHODS`, `VALID_SEARCH_TYPES`, etc.) are also here.
- **SSE streaming**: Used for long-running experiment execution in `app/routes/experiments.py`.

## Database

- **Local / self-hosted**: SQLite at `data/ragas.db` (created on first run via `db/init.py`), WAL mode enabled
- **Server / production**: PostgreSQL via `DATABASE_URL` env var (e.g. Neon) — auto-detected in `db/init.py`
- Schema and all migrations in `db/init.py` — no separate migration files
- Query functions also live in `db/init.py` (single-module data layer)

## Deployment Modes

- **Self-host**: `docker compose up --build` — serves on `PORT` (default 8000), SQLite storage in `./data/`
- **Server (Northflank + Neon)**: Dockerfile exposes port 3000, `PORT` set by platform, `DATABASE_URL` points to Neon PostgreSQL
- **Local dev**: `uvicorn main:app --reload` + `cd frontend && npm run dev` (Vite on :5173)

## Environment Variables

- `OPENAI_API_KEY` (required) — OpenAI API access
- `SESSION_SECRET` (set in production) — signs login session cookies; unset = logins reset on restart
- `RAGAS_API_KEY` (optional) — machine Bearer token (admin identity); also gates open mode
- `DATABASE_URL` (optional) — PostgreSQL connection string; defaults to SQLite if unset
- `PORT` (optional) — server port; defaults to 3000 in Dockerfile, 8000 in docker-compose
- `CORS_ORIGINS` (optional) — comma-separated allowed origins (default: `localhost:3000,localhost:5173`)
- See `.env.example` for full list: storage paths, default models, timeouts, batch sizes, suggestion thresholds

## Testing

- pytest with `asyncio_mode = auto` in `pytest.ini`
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`
- `tests/conftest.py` provides: `tmp_db` (fresh SQLite), `sample_project`, `sample_texts`, `sample_chunks`, `mock_openai_embeddings`, `mock_chat_completion`
- Unit tests cover pipeline components; integration tests hit the FastAPI app

## Conventions

- Python: PEP 8, type annotations on function signatures
- Frontend: TypeScript strict, Tailwind for styling
- New route modules: define `router = APIRouter(prefix=..., tags=[...])`, register in `app/__init__.py`
- New metrics: add async function in `evaluation/metrics/`, import in `scoring.py`, add to `ALL_METRICS`

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

## Preferred Runners
- use python3 instead of python, when running python files