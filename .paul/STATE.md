# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-04-02)

**Core value:** AI engineers can systematically build, test, compare, and improve RAG pipelines against multiple LLM providers in one integrated platform.
**Current focus:** Milestone v0.3 Process Flow & Fixes

## Current Position

Milestone: v0.3 Process Flow & Fixes (v0.3.0)
Phase: 16 of 19 (Build — Save & Use RAG Config)
Plan: Not started
Status: Ready to plan
Last activity: 2026-04-03 — Phase 15 complete, transitioned to Phase 16

Progress:
- Milestone: [███░░░░░░░] 33% (2/6 phases)
- Phase 16: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Idle — ready for next PLAN]
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

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| Glean API docs not yet obtained | v0.1 Init | M | Future milestone |
| Database migration tooling needed | v0.1 Audit | S | Future milestone |

### Git State

Last commit: pending (phase 15 commit)
Branch: main
Feature branches merged: all v0.2 branches merged

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-04-03
Stopped at: Phase 15 complete, ready to plan Phase 16
Next action: /paul:plan for Phase 16
Resume file: .paul/ROADMAP.md

---
*STATE.md -- Updated after every significant action*
