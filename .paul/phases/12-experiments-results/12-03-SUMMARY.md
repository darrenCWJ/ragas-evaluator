---
phase: 12-experiments-results
plan: 03
subsystem: ui
tags: [react, comparison, timeline, sse, tailwind]

requires:
  - phase: 12-01
    provides: Experiment CRUD, ExperimentList, SSE runner
  - phase: 12-02
    provides: ExperimentResults, score bar pattern, humanizeMetric, QuestionResultRow
provides:
  - ExperimentCompare — side-by-side multi-experiment comparison view
  - ExperimentHistory — chronological timeline with score trend
  - API client compareExperiments() and fetchExperimentHistory()
affects: [13-feedback-loop-polish]

tech-stack:
  added: []
  patterns: [multi-select comparison, lazy-load on expand, sparkline trend dots]

key-files:
  created:
    - frontend/src/components/experiment/ExperimentCompare.tsx
    - frontend/src/components/experiment/ExperimentHistory.tsx
  modified:
    - frontend/src/lib/api.ts
    - frontend/src/pages/ExperimentPage.tsx

key-decisions:
  - "Kept score utilities in ExperimentResults rather than extracting to shared file — only 2 consumers"
  - "History lazy-loads on first expand to avoid unnecessary API call"
  - "Compare button disabled at <2 and >5 selections with tooltip"

patterns-established:
  - "Multi-select checkbox coexisting with single-select card click"
  - "Lazy-load data on disclosure expand with hasLoaded guard"
  - "HTTP status-specific error differentiation (409/413 vs generic)"

duration: ~45min
started: 2026-04-02T21:00:00Z
completed: 2026-04-02T21:45:00Z
---

# Phase 12 Plan 03: Experiment Comparison & History Summary

**Side-by-side experiment comparison with multi-select, aggregate metric highlights, per-question expandable comparison, and historical timeline with score trend sparkline**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Started | 2026-04-02T21:00:00Z |
| Completed | 2026-04-02T21:45:00Z |
| Tasks | 4 completed (3 auto + 1 checkpoint) |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Multi-Experiment Comparison Selection | Pass | Checkboxes on completed experiments, Compare Selected button |
| AC-2: Comparison Aggregate Metrics with Delta | Pass | Bars per experiment, best score highlighted |
| AC-3: Per-Question Comparison Table | Pass | Expandable rows with per-experiment response/metrics |
| AC-4: History Timeline | Pass | Reverse chronological, score badges, RAG config name |
| AC-5: Empty and Error States | Pass | Empty messages for comparison and history |
| AC-6: Compare API Error Differentiation | Pass | 409/413 specific messages, no retry, close only |
| AC-7: Client-Side Selection Bounds | Pass | Disabled at <2 and >5 with tooltip |

## Accomplishments

- Built ExperimentCompare component (496 lines) with multi-select comparison, aggregate metrics with best-score highlights, and per-question expandable comparison table
- Built ExperimentHistory component (330 lines) with lazy-loaded chronological timeline, score trend sparkline, and collapsible section
- Extended API client with CompareResult/CompareQuestionData/HistoryExperiment types and compareExperiments/fetchExperimentHistory functions
- Integrated both components into ExperimentPage with independent checkbox multi-select (coexisting with card click for single-select)

## Task Commits

All changes are uncommitted — awaiting phase-level commit after UNIFY.

| Task | Status | Type | Description |
|------|--------|------|-------------|
| Task 1: API client | Complete | feat | CompareResult, CompareQuestionData, HistoryExperiment types + compareExperiments(), fetchExperimentHistory() |
| Task 2: ExperimentCompare | Complete | feat | Side-by-side comparison with aggregate metrics, per-question table, 409/413 error handling |
| Task 3: ExperimentHistory | Complete | feat | Chronological timeline, sparkline trend, lazy-load on expand |
| Checkpoint: Human verify | Complete | verify | User approved comparison and history views |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `frontend/src/components/experiment/ExperimentCompare.tsx` | Created (496 lines) | Side-by-side experiment comparison with aggregate metrics and per-question table |
| `frontend/src/components/experiment/ExperimentHistory.tsx` | Created (330 lines) | Chronological timeline with score trend sparkline |
| `frontend/src/lib/api.ts` | Modified (+275 lines) | CompareResult, CompareQuestionData, HistoryExperiment types; compareExperiments(), fetchExperimentHistory() |
| `frontend/src/pages/ExperimentPage.tsx` | Modified (+196 lines) | Integrated comparison multi-select and history section |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Score utilities kept in ExperimentResults | Only 2 consumers, extraction adds complexity without benefit | Phase 13 may extract if more consumers appear |
| History lazy-loads on expand | Prevents unnecessary API call when section is collapsed | Better performance on page load |
| Checkbox multi-select independent from card click | Users need both: select for comparison AND click for runner/results | Two parallel interaction patterns on experiment cards |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | None |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Plan executed as written.

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ○ | Not invoked during APPLY — components built using existing patterns from ExperimentResults |

**Note:** Skill gap documented. Components follow established design patterns from prior plans.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- All Phase 12 (Experiments & Results) functionality complete
- Experiment creation, runner, results, comparison, and history all functional
- Foundation set for Phase 13 feedback loop and polish

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 12-experiments-results, Plan: 03*
*Completed: 2026-04-02*
