# Ragas LLM Testing & Improvement Platform

## What This Is

A self-hosted platform to build custom RAG bots, generate and annotate test questions, evaluate against multiple LLM models (OpenAI & Glean), and iteratively improve accuracy through structured experiments and actionable suggestions. Built on an existing foundation of 27 Ragas evaluation metrics already deployed with a web UI and API.

## Core Value

AI engineers can systematically build, test, compare, and improve RAG pipelines against multiple LLM providers — with human-reviewed test sets, automated evaluation, and actionable improvement suggestions — in one integrated platform.

## Current State

| Attribute | Value |
|-----------|-------|
| Type | Application |
| Version | 0.0.0 |
| Status | v0.1.0 Complete |
| Last Updated | 2026-04-02 (after Phase 8) |

**Existing Functionality:**
- 27 Ragas evaluation metrics (RAG, NLP, general purpose, agent, SQL)
- Web UI for single-query evaluation (dark theme, Tailwind-inspired)
- REST API (FastAPI local + Vercel serverless)
- Test question generator module (basic, pre-refactor)
- CSV batch processing

## Requirements

### Core Features

- Upload documents and build configurable RAG pipelines (chunking, embedding, retrieval)
- Generate test Q&A with personas and human annotation (approve/reject/edit)
- Run structured experiments against multiple models (OpenAI + Glean) using approved test sets
- View results with side-by-side comparison and actionable improvement suggestions
- Iterate: re-configure pipeline based on suggestions, re-test, measure impact

### Validated (Shipped)

- [x] 27 Ragas evaluation metrics — v0.0.0
- [x] Web UI for single-query evaluation — v0.0.0
- [x] REST API (evaluate + metrics endpoints) — v0.0.0
- [x] Basic test question generator — v0.0.0
- [x] CSV batch processing — v0.0.0

### Active (In Progress)

- [ ] Frontend rewrite: React+Vite+Tailwind SPA with guided stepper workflow (v0.2.0)
- [x] Build stage UI: document upload, chunking, embedding, RAG config, test query, pipeline status — v0.2.0-dev (Phase 10)
- [x] Test stage UI: test set generation, question browsing, inline annotation (approve/reject/edit), bulk actions — v0.2.0-dev (Phase 11)

### Validated (Shipped)

- [x] Docker + Railway migration — v0.1.0-dev
- [x] Document pipeline & chunking engine — v0.1.0-dev
- [x] Embedding & vector storage (OpenAI, sentence-transformers, BM25, hybrid search) — v0.1.0-dev
- [x] RAG bot with single-shot & multi-step query modes — v0.1.0-dev
- [x] Test set generation & human annotation workflow — v0.1.0-dev
- [x] Multi-model experiment runner with SSE progress & results UI — v0.1.0-dev
- [x] Results dashboard with comparison, suggestions engine & history timeline — v0.1.0-dev
- [x] Feedback loop & iteration workflow (apply suggestions, delta comparison, export) — v0.1.0

### Planned (Next)

None — all planned features covered by v0.2.0 phases.

### Out of Scope

- Multi-user / RBAC (single-team use initially)
- LLM providers beyond OpenAI + Glean (future milestone)
- ML-powered suggestion engine (rule-based first)
- Frontend framework rewrite — completed in v0.2 (React+Vite+Tailwind SPA)

## Target Users

**Primary:** AI engineers and developers evaluating RAG systems
- Need systematic testing across models
- Want to iterate on retrieval strategy, chunking, embeddings
- Currently stitching together multiple tools manually

## Constraints

### Technical Constraints

- Ragas 0.4.3+ required (v0.4 `@experiment` decorator API)
- OpenAI API dependency for LLM inference and embeddings
- Glean API access needed for Phase 6 (docs not yet obtained)
- SQLite for experiment storage (no external DB server)
- ChromaDB (dev) / Pinecone (prod) for vector storage

### Business Constraints

- Single-team use — no multi-tenant requirements
- Must preserve existing evaluation functionality during migration
- Glean API documentation and credentials needed before Phase 6

## Key Decisions

| Decision | Rationale | Date | Status |
|----------|-----------|------|--------|
| ChromaDB for dev, Pinecone for prod | Fast local dev loop, managed prod scaling | 2026-03-31 | Active |
| SQLite over filesystem | Experiment comparison needs SQL queries | 2026-03-31 | Active |
| Human annotation before testing | Bad reference answers produce misleading metrics | 2026-03-31 | Active |
| Rule-based suggestions over ML | Simple, explainable, no training data needed | 2026-03-31 | Active |
| Docker + Railway over Vercel | RAG building needs sustained compute, long-running processes | 2026-03-31 | Active |
| Extend vanilla HTML/CSS/JS | No framework rewrite — add pages incrementally | 2026-03-31 | Superseded |
| React+Vite+Tailwind SPA | Modern SPA replacing vanilla pages, dark theme carried forward | 2026-04-02 | Active |
| Ragas v0.4 @experiment decorator | Replaces deprecated evaluate(), per-row control, auto-save | 2026-03-31 | Active |

## Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Test coverage | 70%+ per phase | - | Not started |
| API contract validation | All endpoints return expected schema | - | Not started |
| Experiment reproducibility | Same config produces same results | - | Not started |
| Docker build | Clean build, no warnings | - | Not started |
| Suggestion accuracy | Suggestions match known failure patterns | - | Not started |

## Tech Stack / Tools

| Layer | Technology | Notes |
|-------|------------|-------|
| Backend | FastAPI (Python 3.11) | Already in use, async-native |
| Database | SQLite | File-based, queryable, no server |
| Vector Store (Dev) | ChromaDB | In-process, no account needed |
| Vector Store (Prod) | Pinecone | Managed, hybrid search support |
| Embeddings | OpenAI text-embedding-3-*, sentence-transformers, BM25 | Dense, sparse, hybrid |
| Evaluation | Ragas 0.4.3+ | 27 metrics, @experiment decorator |
| Test Generation | Ragas TestsetGenerator | Persona-based, pre-chunked data |
| Frontend | React 18 + Vite 6 + TypeScript 5 + Tailwind 3 | SPA at /app, dark theme carried forward |
| Deployment | Docker + Railway | Long-running process support |

## Links

| Resource | URL |
|----------|-----|
| Ragas Experimentation Docs | https://docs.ragas.io/en/stable/concepts/experimentation/ |
| Ragas Evaluate & Improve RAG | https://docs.ragas.io/en/stable/howtos/applications/evaluate-and-improve-rag/ |
| PLANNING.md | projects/ragas-platform/PLANNING.md |

## Specialized Flows

See: .paul/SPECIAL-FLOWS.md

Quick Reference:
- /frontend-design → Landing pages, dashboard views, comparison view

---
*PROJECT.md -- Updated when requirements or context change*
*Last updated: 2026-04-02 after Phase 11 — Test Generation & Annotation complete*
