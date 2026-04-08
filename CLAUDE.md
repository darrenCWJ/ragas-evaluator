# CLAUDE.md

## Project

RAG Evaluator — an LLM-as-a-judge platform for testing and improving RAG chatbots. Configures RAG pipelines, generates synthetic test sets, runs evaluation experiments against 20+ metrics, and produces actionable suggestions.

## Quick Start

```bash
# Backend
pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY
uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

## Test

```bash
pytest                          # all tests
pytest tests/unit/              # unit only
pytest tests/integration/       # integration only
pytest --cov=app --cov=evaluation --cov=pipeline --cov-report=term-missing
```

## Database

- SQLite at `data/ragas.db` (created on first run via `db/init.py`)
- WAL mode enabled
- Schema migrations in `db/init.py`

## Architecture

```
main.py → app/ (FastAPI)
            ├── routes/        14 route modules
            ├── models.py      Pydantic models
         pipeline/             RAG engine (chunking, embedding, retrieval, generation)
         evaluation/
            ├── metrics/       30 metric wrappers (Ragas + custom)
            ├── scoring.py     Metric orchestration
            ├── suggestions.py Rule-based suggestion engine
            └── testgen.py     Synthetic test generation
         db/init.py            Schema + queries
         frontend/             React 18 + Vite + Tailwind SPA
```

## Key Patterns

- **Route modules** in `app/routes/` each define a `router = APIRouter(prefix=..., tags=[...])`
- **Metrics** in `evaluation/metrics/` each export a single async function; wired through `evaluation/scoring.py`
- **SSE streaming** used for long-running experiment execution (`experiments.py`)
- **ChromaDB** for vector storage, **BM25** for sparse retrieval, hybrid mode available
- **Multi-provider LLM**: OpenAI, Anthropic, Google GenAI via `pipeline/llm.py`

## Environment Variables

- `OPENAI_API_KEY` (required) — OpenAI API access
- `GLEAN_API_KEY` (optional) — Glean enterprise search
- `CORS_ORIGINS` (optional) — comma-separated allowed origins

## Conventions

- Python: PEP 8, type annotations on function signatures
- Tests: pytest with `@pytest.mark.unit` / `@pytest.mark.integration` markers
- Async: `asyncio_mode = auto` in pytest.ini
- Frontend: TypeScript strict, Tailwind for styling
