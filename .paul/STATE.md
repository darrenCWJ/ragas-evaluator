# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-04-03)

**Core value:** AI engineers can systematically build, test, compare, and improve RAG pipelines against multiple LLM providers in one integrated platform.
**Current focus:** Milestone v0.3 Process Flow & Fixes — COMPLETE

## Current Position

Milestone: v0.3 Process Flow & Fixes (v0.3.0) — COMPLETE
Phase: 19 of 19 (Analyze Fixes) — Complete
Plan: 19-01 complete
Status: Milestone complete, ready for next milestone
Last activity: 2026-04-03 — Phase 19 complete, v0.3 milestone complete

Progress:
- Milestone: [██████████] 100% (6/6 phases)
- Phase 19: [██████████] 100%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone finished]
```

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| React + Vite + Tailwind | v0.2 init | Modern SPA stack, dark theme carried forward |
| Single-page app with stepper | v0.2 init | Guided pipeline workflow, no page-hopping |
| Backend API unchanged | v0.2 init | Frontend-only rewrite, all FastAPI endpoints stay |
| Refresh callbacks for mutation-driven list updates | Phase 10 | Reusable pattern for future config panels |
| Dynamic form fields based on config type | Phase 10 | Pattern for conditional form sections |
| fetch ReadableStream for SSE over POST | Phase 12 | EventSource is GET-only; established SSE-over-POST pattern |
| Score bar pattern with humanizeMetric | Phase 12 | Reusable across results, comparison, history |
| Lazy-load history on expand | Phase 12 | Prevents unnecessary API calls |
| Inline confirmation for Apply (not modal) | Phase 13 | Consistent with existing patterns, less disruptive |
| Raw fetch for export (blob, not JSON) | Phase 13 | exportExperiment uses fetch directly for file download |
| Always render ExperimentDelta | Phase 13 | Component handles no-baseline gracefully |
| useStageCompletion with location-based refetch | Phase 13 | Immediate feedback after user actions on stages |
| Inline dismissable banner for delete errors | Phase 15 | Reusable pattern for delete failure feedback |
| Help text as static p elements below labels | Phase 15 | Simple, accessible, no tooltip dependencies |
| Enterprise audit on Phase 16 plan: 3 must-have + 2 strongly-recommended applied | Phase 16 | Plan strengthened for route ordering, authorization, error handling |
| Expanded endpoint pattern with _expand_rag_config helper | Phase 16 | Reusable for future entity expansion endpoints |
| Route ordering: static paths before path params in FastAPI | Phase 16 | Must maintain for all future /rag-configs/* routes |
| Enterprise audit on Phase 17 plan: 1 must-have + 2 strongly-recommended applied | Phase 17 | Plan strengthened for persona validation, AC max-count, error-path verification |
| bg-input for form controls, bg-elevated for containers, bg-deep for inset blocks | Phase 17 | Design token mapping pattern for dark theme consistency |
| Functional setState with .map() for array updates | Phase 17 | Avoids TS array index type inference issues |
| Enterprise audit on Phase 18 plan: 1 must-have + 3 strongly-recommended applied | Phase 18 | Plan strengthened for atomic reset, audit logging, error-path verification |
| Enterprise audit on Phase 19 plan: 1 must-have + 1 strongly-recommended applied | Phase 19 | Plan strengthened for experiment row serialization, error-path verification |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| Glean API docs not yet obtained | v0.1 Init | M | Future milestone |
| Database migration tooling needed | v0.1 Audit | S | Future milestone |

### Git State

Last commit: 52d00cf (pre-Phase 18)
Branch: main
Feature branches merged: all v0.2 branches merged

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-04-03
Stopped at: v0.3 milestone complete
Next action: /paul:milestone or /paul:discuss-milestone for next milestone
Resume file: .paul/ROADMAP.md

---
*STATE.md -- Updated after every significant action*
