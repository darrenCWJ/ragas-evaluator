# RAG Evaluator Codemaps

**Last Updated:** 2026-04-24

This directory contains architectural maps of the RAG Evaluator codebase, organized by functional area.

## Overview

RAG Evaluator is a distributed LLM-as-a-judge platform for testing RAG pipelines. The codebase is split into:

1. **Main Application** (`/`) — FastAPI server, web UI, metrics, suggestion engine
2. **Worker Service** (`/worker`) — Offloaded knowledge graph construction
3. **Frontend** (`/frontend`) — React/TypeScript SPA

## Codemaps

| Area | Purpose | Entry Point |
|------|---------|-------------|
| [Worker Service](./worker.md) | Knowledge graph builder — memory-intensive async task processor | `worker/main.py` |
| [Main App Architecture](./main.md) | RAG pipeline, evaluation metrics, test generation, suggestions | `main.py` |
| [Frontend](./frontend.md) | React SPA — project management, experiment runner, results viewer | `frontend/src/main.tsx` |

## Key Abstractions

### God Nodes (Most Connected)
From the graphify report, these are the core abstractions that most other code depends on:

1. `get_db()` (119 edges) — Database connection factory
2. `request()` (66 edges) — HTTP client for worker/external APIs
3. `chunk_text()` (39 edges) — Chunking pipeline
4. `BotResponse` (36 edges) — Unified bot connector response type
5. `TestGenRequest` (26 edges) — Test generation request model
6. `TestSetCreate` (26 edges) — Test set creation request
7. `QuestionAnnotation` (26 edges) — Human annotation request
8. `BulkAnnotation` (26 edges) — Bulk annotation request
9. `Citation` (24 edges) — Source citation model
10. `chat_completion()` (21 edges) — LLM completion wrapper

### Community Structure (43 Communities)

Key functional clusters:
- **Suggestions & Annotation API** — Suggestion generation, human feedback
- **Test Generation & Bulk Operations** — Testset synthesis, bulk actions
- **Multi-LLM Judge & Source Verification** — Multi-model evaluation, citation validation
- **Retrieval & Embedding Dispatch** — RAG retrieval, embedding selection
- **Custom Metrics Engine** — Per-project metric definitions
- **Frontend Annotation & API Client** — Web UI components and API integration

See `graphify-out/GRAPH_REPORT.md` for the full community map.

## Development Workflow

### Before Modifying Code

1. Check graphify report for related nodes and communities
2. Read the relevant codemap for architectural context
3. Identify god nodes that may be affected

### After Modifying Code

Keep the knowledge graph current:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

## Database Schema

Both main app and worker share the same database (PostgreSQL or SQLite):

- **Main app** initializes schema via `db/init.py`
- **Worker** initializes its KG-specific tables via `worker/db/init.py`
- Both can be run against the same connection string

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — Project overview, commands, architecture at a glance
- [README.md](../../README.md) — Problem statement, design principles, metrics guide
- [docs/FEATURES.md](../FEATURES.md) — Feature-by-feature guide with motivation
