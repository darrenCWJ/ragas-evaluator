---
phase: 12-experiments-results
plan: 01
subsystem: ui
tags: [react, sse, experiment, streaming, typescript]

requires:
  - phase: 11-test-generation-annotation
    provides: test sets with approved questions, annotation workflow
  - phase: 10-document-rag-pipeline
    provides: RAG config panel patterns, refresh callback conventions

provides:
  - Experiment CRUD API client with TypeScript types
  - SSE streaming helper for POST-based server-sent events
  - ExperimentCreate form with validation and error handling
  - ExperimentList with status badges and delete confirmation
  - ExperimentRunner with live progress bar and connection resilience

affects: [12-02 results dashboard, 12-03 comparison and history]

tech-stack:
  added: []
  patterns: [SSE POST streaming via fetch ReadableStream, discriminated union RunState]

key-files:
  created:
    - frontend/src/components/experiment/ExperimentCreate.tsx
    - frontend/src/components/experiment/ExperimentList.tsx
    - frontend/src/components/experiment/ExperimentRunner.tsx
  modified:
    - frontend/src/lib/api.ts
    - frontend/src/pages/ExperimentPage.tsx

key-decisions:
  - "fetch ReadableStream over EventSource for POST-based SSE"
  - "Discriminated union type for RunState (idle/running/completed/error/connection_lost)"
  - "Runner only for pending experiments (backend returns 409 for non-pending)"

patterns-established:
  - "SSE POST streaming: fetch + ReadableStream + manual event parsing"
  - "Connection resilience: onConnectionError callback with last known progress"
  - "Metric toggle chips: Set<string> state with visual toggle buttons"

duration: ~30min
completed: 2026-04-02T06:15:00Z
---

# Phase 12 Plan 01: Experiment Creation & SSE Runner Summary

**Experiment stage UI with CRUD, metric selection, and live SSE progress tracking via fetch ReadableStream**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-04-02 |
| Tasks | 3 auto + 1 checkpoint |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Experiment Creation | Pass | Form creates experiment, appears in list with pending status |
| AC-1b: Creation Error Handling | Pass | API errors display inline, form preserved on error |
| AC-2: Experiment List with Status | Pass | Yellow pending, blue/pulse running, green completed, red failed |
| AC-3: Live Experiment Runner | Pass | SSE progress bar, elapsed timer, current question display |
| AC-3b: SSE Connection Failure | Pass | Connection-lost state with last progress + Refresh Status button |
| AC-3c: Form Validation | Pass | Disabled submit until name + test set + RAG config filled |

## Accomplishments

- Experiment API client with 5 CRUD functions + SSE streaming helper parsing POST-based server-sent events
- ExperimentCreate form filtering test sets to approved-only, with client-side validation and inline API error display
- ExperimentRunner with discriminated union state machine (idle → running → completed/error/connection_lost), live progress bar, elapsed timer, cancel support, and connection resilience

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `frontend/src/lib/api.ts` | Modified | Added Experiment/ExperimentResult types, 5 CRUD functions, SSE streaming helper with event parsing |
| `frontend/src/pages/ExperimentPage.tsx` | Modified | Replaced stub with assembled page: create form + list + runner |
| `frontend/src/components/experiment/ExperimentCreate.tsx` | Created | Form with test set/RAG config dropdowns, validation, error display |
| `frontend/src/components/experiment/ExperimentList.tsx` | Created | Card list with status badges, selection state, delete confirmation |
| `frontend/src/components/experiment/ExperimentRunner.tsx` | Created | Metric toggle chips, SSE progress bar, connection resilience |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minimal — TypeScript strictness fix |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Negligible — one TS fix, plan executed as specified

### Auto-fixed Issues

**1. TypeScript strict null check on STATUS_STYLES lookup**
- **Found during:** Task 2 (ExperimentList)
- **Issue:** `STATUS_STYLES[exp.status]` possibly undefined per strict TS
- **Fix:** Added non-null assertion on fallback: `?? STATUS_STYLES["pending"]!`
- **Verification:** `tsc --noEmit` passes clean

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| fetch ReadableStream for SSE | Backend uses POST for /run endpoint; EventSource is GET-only | Established SSE-over-POST pattern for future use |
| Runner only for pending status | Backend returns 409 for non-pending experiments (audit finding) | Prevents confusing UX errors |
| Discriminated union for RunState | 5 distinct UI states need type-safe handling | Clean state machine, no invalid states possible |

## Skill Audit

Skill audit: `/frontend-design` required skill was loaded before APPLY ✓

## Next Phase Readiness

**Ready:**
- Experiment CRUD and list available for Plans 12-02 and 12-03
- API client has `fetchExperimentResults` ready for results dashboard
- SSE pattern established for any future streaming needs

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 12-experiments-results, Plan: 01*
*Completed: 2026-04-02*
