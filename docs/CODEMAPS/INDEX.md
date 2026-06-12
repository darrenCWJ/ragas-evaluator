# Tribunal Codemaps

**Last Updated:** 2026-06-13

This directory contains architectural maps of the Tribunal (RAG Evaluator) codebase, organized by functional area.

## Overview

Tribunal is an LLM-as-a-judge platform for testing AI agents — internal RAG pipelines built in-app, or external agents called via API — with a full diagnose → fix → verify loop. The codebase is split into:

1. **Main Application** (`/`) — FastAPI server, auth, RAG pipeline, 26 metrics, suggestion engine + prompt doctor, Skill Arena, insights (quality audit / coverage / breakdowns / CI gate)
2. **Worker Service** (`/worker`) — offloaded KG construction and persona generation; imports the main app's shared modules (no forked code)
3. **Frontend** (`/frontend`) — React/TypeScript SPA with login, guided Start flow, and live experiment streaming

## Codemaps

| Area | Purpose | Entry Point |
|------|---------|-------------|
| [Main App Architecture](./main.md) | Routes, services, pipeline, evaluation, auth, database | `main.py` |
| [Worker Service](./worker.md) | KG builds + persona generation on shared modules | `worker/main.py` |
| [Frontend](./frontend.md) | React SPA — auth, guided flow, runner, analysis, Skill Arena | `frontend/src/main.tsx` |

## Key Abstractions

The load-bearing pieces most other code depends on:

| Abstraction | Where | Why it matters |
|---|---|---|
| `get_db()` / `get_thread_db()` | `db/init.py` | Single data layer, SQLite/PostgreSQL dual backend, raw SQL (no ORM) |
| `chat_completion()` | `pipeline/llm.py` | All LLM calls route here (provider detection + gateway mode) |
| `with_backoff()` | `pipeline/retry.py` | Retry/backoff wrapper used by every LLM/HTTP call path |
| `BotConnector` protocol | `pipeline/bot_connectors/base.py` | 7 connectors; all accept `system_context` and `history` kwargs |
| `evaluate_experiment_row()` | `evaluation/scoring.py` | Metric dispatch (signature groups incl. metadata-gated metrics) |
| `ProgressStore` | `app/services/progress.py` | Lock-guarded run state shared by runners and SSE observers |
| `_AuthMiddleware` | `app/__init__.py` | Sessions + per-project access; open mode until first user registers |
| `GUARDRAIL_SNIPPETS` | `evaluation/suggestions.py` | Applyable prompt fixes tied to failure signals |

## Database Schema

Main app and worker share one database (SQLite or PostgreSQL via `DATABASE_URL`), initialized and migrated **only** by `db/init.py` (the worker imports the same module). Core tables: `users`, `project_members`, `projects`, `documents`, `chunk_configs`, `chunks`, `embedding_configs`, `rag_configs`, `test_sets`, `test_questions`, `bot_configs`, `experiments`, `experiment_results`, `suggestions`, `skills`, `skill_trials`, `skill_trial_results`, `knowledge_graphs`, `multi_llm_evaluations`, `personas`, `custom_metrics`, `human_annotations`, `external_baselines`, `source_verifications`.

## Development Workflow

1. Read the relevant codemap before structural changes.
2. New route modules: `router = APIRouter(prefix=..., tags=[...])`, register in `app/__init__.py`; project-scoped paths get access control from the middleware automatically.
3. New metrics: async module in `evaluation/metrics/`, wire into `scoring.py` (`ALL_METRICS`, `_METRIC_MODULES`, a signature group, and the dependency set) and the frontend metric catalog (`frontend/src/components/experiment/runner/MetricSelection.tsx`).
4. Verify: `ruff check .`, `pytest tests/unit tests/integration -m "not slow"`, `cd frontend && npx tsc --noEmit && npm run build && npx eslint src`.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — Project overview, commands, architecture at a glance
- [README.md](../../README.md) — Problem statement, design, metrics guide, deployment
- [docs/FEATURES.md](../FEATURES.md) — Feature-by-feature guide with motivation
- [docs/WORKFLOW.md](../WORKFLOW.md) — End-to-end user walkthrough
- [docs/IMPROVEMENT_PLAN.md](../IMPROVEMENT_PLAN.md) — The v0.4 overhaul audit, plan, and execution log
