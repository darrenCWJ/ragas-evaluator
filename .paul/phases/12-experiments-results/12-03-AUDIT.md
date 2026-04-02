# Enterprise Plan Audit Report

**Plan:** .paul/phases/12-experiments-results/12-03-PLAN.md
**Audited:** 2026-04-02
**Verdict:** Conditionally acceptable

---

## 1. Executive Verdict

**Conditionally acceptable.** The plan is structurally sound — clear vertical slice, well-defined ACs, proper reuse of established patterns (LoadState, score utilities, keyboard accessibility). However, it had gaps in API error differentiation (compare endpoint returns 409 and 413 for distinct validation failures that need distinct UX), missing client-side selection bounds enforcement, and underspecified interaction model for dual-selection (compare multi-select vs. single-select for runner/results).

After applying must-have and strongly-recommended upgrades, plan is enterprise-ready for a frontend presentation layer.

## 2. What Is Solid

- **LoadState discriminated union pattern** reused from 12-01 and 12-02 — proven, type-safe, consistent. No change needed.
- **Boundaries section** is precise: protects backend, prior components, and explicitly names Phase 13 items as off-limits. Prevents scope creep.
- **Backend endpoint documentation** in context section — specific paths, response shapes, query parameter format. Removes ambiguity during APPLY.
- **Score utility reuse strategy** — pragmatic "reuse or extract" approach rather than blind duplication.
- **Verification checklist** includes both `tsc --noEmit` and `npm run build` — catches type errors and bundler issues independently.
- **Checkpoint placement** — human-verify after all auto tasks is correct for a UI-heavy plan.

## 3. Enterprise Gaps Identified

1. **API error differentiation missing:** Compare endpoint returns 409 (test set mismatch / not completed) and 413 (payload too large). Plan specified generic "error + retry" pattern, but retry is pointless for both — user must change their selection. Without differentiation, 409 looks like a system error instead of a user-correctable condition.

2. **No client-side max selection enforcement:** Backend limits to 2-5 experiments. Plan only specified "disabled unless 2+" with no upper bound check. Users selecting 6+ would hit a 400 error after an API call instead of being prevented client-side.

3. **ExperimentList dual-selection model unspecified:** Task 2 adds checkbox multi-select for compare alongside existing card-click single-select for runner/results. Without explicit clarification, implementer could conflate the two selection models, creating broken UX where checking a compare box also selects for results view.

4. **Keyboard accessibility gap in comparison rows:** Task 2 specifies expandable per-question rows but doesn't require keyboard support. QuestionResultRow already has this (role="button", aria-expanded, Enter/Space) — comparison rows should match.

5. **History fetch lifecycle:** Component mounted in a collapsed section would trigger API call on page load even when user doesn't open it. Unnecessary network request.

## 4. Upgrades Applied to Plan

### Must-Have (Release-Blocking)

| # | Finding | Plan Section Modified | Change Applied |
|---|---------|----------------------|----------------|
| 1 | Compare 409/413 error differentiation | AC-5 → AC-6 (new), Task 2 error state | Added AC-6 with specific Given/When/Then for 409 and 413. Task 2 now specifies distinct error handling: 409 → specific message + close (no retry), 413 → "select fewer" + close, other → generic + retry |
| 2 | Client-side max selection (2-5) | AC-7 (new), Task 2 integration | Added AC-7 for selection bounds. Task 2 now specifies button disabled at <2 and >5 with tooltip "Maximum 5 experiments" |

### Strongly Recommended

| # | Finding | Plan Section Modified | Change Applied |
|---|---------|----------------------|----------------|
| 1 | Dual-selection model clarity | Task 2 integration section | Clarified checkbox selection (multi) coexists with card click (single-select). Checkboxes only on completed experiments. States are independent |
| 2 | Keyboard accessibility on comparison rows | Task 2 action | Added requirement for role="button", tabIndex, aria-expanded, Enter/Space handlers matching QuestionResultRow pattern |
| 3 | History lazy-load on first expand | Task 3 data loading | Changed from "on mount" to "on first expand" with hasLoaded flag to prevent re-fetch on subsequent toggles |

### Deferred (Can Safely Defer)

| # | Finding | Rationale for Deferral |
|---|---------|----------------------|
| 1 | Deduplicating experiment data between list and history API calls | Low impact — separate fetch is simpler and history includes `overall_score` which the list endpoint doesn't compute |
| 2 | Comparison permalink / shareable URL with experiment IDs | UX enhancement not in phase scope |
| 3 | Comparison metric weighting / custom sort | Future enhancement — score sort is sufficient for v0.2 |

## 5. Audit & Compliance Readiness

- **Audit evidence:** Both comparison and history operations are read-only (GET endpoints) — no mutation risk. Low attack surface.
- **Silent failure prevention:** Error differentiation fix ensures users see actionable messages for expected validation failures (409, 413) rather than generic errors that look like system bugs.
- **Post-incident reconstruction:** Frontend is a pure presentation layer. All comparison data sourced from backend. No client-side state mutations that could create data divergence.
- **Ownership & accountability:** ExperimentCompare and ExperimentHistory are self-contained components with clear props interfaces. Integration points in ExperimentPage are well-defined.

## 6. Final Release Bar

- **Must be true before ship:** 409/413 differentiation implemented, selection bounds enforced client-side, keyboard accessible expandable rows
- **Risks if shipped as-is (pre-upgrade):** Users would see confusing generic errors on expected comparison validation failures; could select >5 experiments and get raw API error
- **After upgrades applied:** Plan is enterprise-ready. Would sign off on this for production.

---

**Summary:** Applied 2 must-have + 3 strongly-recommended upgrades. Deferred 3 items.
**Plan status:** Updated and ready for APPLY

---
*Audit performed by PAUL Enterprise Audit Workflow*
*Audit template version: 1.0*
