# Enterprise Plan Audit Report

**Plan:** .paul/phases/12-experiments-results/12-01-PLAN.md
**Audited:** 2026-04-02
**Verdict:** Conditionally acceptable

---

## 1. Executive Verdict

**Conditionally acceptable.** The plan is well-structured with clean task decomposition, solid boundary definitions, and correct pattern reuse from Phases 10-11. However, it contained a backend contract mismatch (runner showing for failed experiments when backend only accepts pending), missing error handling specification, and no SSE connection resilience — all of which could cause confusing UX failures in production. These have been corrected.

Would I approve this for production after fixes? Yes, with the applied upgrades.

## 2. What Is Solid

- **Task decomposition:** API layer → UI components → SSE streaming is correctly layered. Each task has a clear boundary and doesn't bleed into the next.
- **Boundaries section:** Properly protects Build/Test stages, shared hooks, and backend API. No scope creep risk.
- **Pattern reuse:** Refresh callbacks, status badges, inline confirmation — all carry forward from Phases 10-11 without reinventing.
- **Human-verify checkpoint:** Correctly placed after all auto tasks, before plan completion. SSE streaming is visual enough to warrant manual verification.
- **SSE POST recognition:** Plan correctly identifies that `EventSource` is GET-only and the backend uses POST, routing to `fetch + ReadableStream`. This avoids a common implementation mistake.
- **Skills requirement:** `/frontend-design` correctly flagged as blocking.

## 3. Enterprise Gaps Identified

### Gap 1: Status mismatch — runner for "pending/failed" vs backend "pending-only" (CRITICAL)
- Plan Task 3 and ExperimentPage integration both specified showing the runner for "pending/failed" experiments
- Backend `main.py:2506`: `if experiment["status"] != "pending"` → 409 Conflict
- Failed experiments CANNOT be re-run. Showing the Run button for them would produce a confusing 409 error
- **Risk:** User clicks Run on a failed experiment, gets cryptic error, loses trust in the UI

### Gap 2: No error handling for create/run API failures
- AC-1 only covered the happy path
- Backend validates: test set must have approved questions (422), RAG config must belong to project (422), project must exist (404)
- Without frontend error display, these validated rejections would show as generic failures
- **Risk:** User doesn't know WHY creation failed, can't self-correct

### Gap 3: SSE connection resilience unspecified
- Long-running experiments (50+ questions × multiple metrics) can take minutes
- No specification for: network disconnection, browser tab backgrounding, stream read errors
- **Risk:** User sees stuck "running" spinner with no recovery path, has to guess whether experiment completed on backend

### Gap 4: SSE text parsing underspecified
- Plan said "parse SSE events" but didn't specify HOW to parse the text/event-stream format
- SSE over fetch requires manual parsing: `\n\n` delimiters, `event:` and `data:` field extraction, partial chunk handling across ReadableStream reads
- **Risk:** Implementation guesswork leading to missed events or malformed JSON parsing

### Gap 5: No form validation specification
- Create form had no validation rules — empty name, no selections could be submitted
- Backend would catch these but with less helpful error messages than client-side validation
- **Risk:** Unnecessary API roundtrips, poor UX for simple validation

### Gap 6: No initial loading state spec (minor)
- ExperimentPage needs to fetch experiments + test sets + RAG configs on mount
- No mention of loading skeleton or spinner
- **Risk:** Brief flash of empty content before data loads

### Gap 7: Running experiment card visual detail (minor)
- Plan mentions blue/pulse badge for running status but no detail on whether progress appears inline in the card
- **Risk:** Ambiguity for implementer, but manageable

### Gap 8: Delete guard for running experiments (minor)
- Can users delete a running experiment? This could orphan the SSE stream
- Backend may or may not guard against this
- **Risk:** Low — edge case, SSE stream would error naturally

## 4. Upgrades Applied to Plan

### Must-Have (Release-Blocking)

| # | Finding | Plan Section Modified | Change Applied |
|---|---------|----------------------|----------------|
| 1 | Runner showed for failed experiments but backend only accepts pending (409) | Task 3 action, ExperimentPage integration | Changed "pending/failed" → "pending" only, added code reference to main.py:2506 |
| 2 | No error handling for API failures in create flow | AC section, Task 2 action | Added AC-1b (error handling criterion), added API error display and form preservation to ExperimentCreate spec |

### Strongly Recommended

| # | Finding | Plan Section Modified | Change Applied |
|---|---------|----------------------|----------------|
| 1 | SSE connection drop handling missing | Task 3 action, AC section | Added AC-3b (connection failure), added connection-lost UX with "Refresh Status" button, added onConnectionError callback |
| 2 | SSE text parsing underspecified | Task 1 action | Added explicit parsing spec: split on \n\n, parse event:/data: fields, handle partial chunks |
| 3 | No form validation specification | AC section, Task 2 action, Verification | Added AC-3c (form validation), added client-side validation to ExperimentCreate, added verification checks |

### Deferred (Can Safely Defer)

| # | Finding | Rationale for Deferral |
|---|---------|----------------------|
| 1 | Initial loading state for page mount | Standard pattern already established in Phase 10/11 — implementer will naturally add loading states following existing patterns |
| 2 | Running experiment card inline progress | Blue/pulse badge is sufficient visual indicator. Inline progress in cards is an enhancement, not a gap. |
| 3 | Delete guard for running experiments | Edge case. SSE stream would error naturally if experiment is deleted mid-run. Backend may already handle this. Low risk. |

## 5. Audit & Compliance Readiness

**Audit evidence:** Plan produces observable artifacts (experiments in DB with status transitions, SSE events logged). The human-verify checkpoint creates a manual test record.

**Silent failure prevention:** Strengthened. The original plan had two silent failure paths (failed experiment 409, dropped SSE connection). Both now have explicit error display requirements.

**Post-incident reconstruction:** Backend logs experiment status transitions with timestamps. Frontend SSE events provide client-side progress trail. Connection-lost state preserves last known progress count.

**Ownership:** Clear — frontend-only changes against stable backend API. No shared-state mutations beyond experiment CRUD through established endpoints.

## 6. Final Release Bar

**What must be true before shipping:**
- All 5 applied upgrades are implemented (2 must-have, 3 strongly-recommended)
- Runner only appears for pending experiments — verified against backend contract
- SSE connection loss doesn't leave stuck UI state
- Form validation prevents empty submissions
- Human-verify checkpoint passes with all 10 verification items

**Risks remaining if shipped as-is (post-fixes):**
- No automatic SSE reconnection (user must manually refresh) — acceptable for v0.2
- No inline progress on experiment cards when running — cosmetic only
- Delete of running experiment is unguarded — very low probability edge case

**Sign-off:** With the applied upgrades, I would sign my name to this plan for production execution.

---

**Summary:** Applied 2 must-have + 3 strongly-recommended upgrades. Deferred 3 items.
**Plan status:** Updated and ready for APPLY

---
*Audit performed by PAUL Enterprise Audit Workflow*
*Audit template version: 1.0*
