# Roadmap: Ragas LLM Testing & Improvement Platform

## Overview

Transform an existing Ragas evaluation tool (27 metrics, web UI, API) into a full platform for building RAG bots, generating human-reviewed test sets, running structured experiments across models, and iterating on pipeline quality with actionable suggestions.

## Completed Milestones

### v0.1 Initial Release (v0.1.0)

Status: Complete
Phases: 8 of 8 complete
Completed: 2026-04-02

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Docker + Railway Migration | 1 | Complete | 2026-03-31 |
| 2 | Document Pipeline & Chunking Engine | 2 | Complete | 2026-03-31 |
| 3 | Embedding & Vector Storage | 2 | Complete | 2026-03-31 |
| 4 | RAG Bot (Single-Shot & Multi-Step) | 2 | Complete | 2026-03-31 |
| 5 | Test Set Generation & Annotation | 2 | Complete | 2026-04-01 |
| 6 | Multi-Model Support & Experiment Runner | 3 | Complete | 2026-04-01 |
| 7 | Results Dashboard & Improvement Suggestions | 2 | Complete | 2026-04-01 |
| 8 | Feedback Loop & Iteration | 2 | Complete | 2026-04-02 |

### v0.2 Frontend Rewrite (v0.2.0)

Status: Complete
Phases: 5 of 5 complete
Completed: 2026-04-02

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 9 | Foundation & Design System | 1 | Complete | 2026-04-02 |
| 10 | Document & RAG Pipeline | 2 | Complete | 2026-04-02 |
| 11 | Test Generation & Annotation | 2 | Complete | 2026-04-02 |
| 12 | Experiments & Results | 3 | Complete | 2026-04-02 |
| 13 | Feedback Loop & Polish | 2 | Complete | 2026-04-02 |

## Current Milestone

**v0.3 Process Flow & Fixes** (v0.3.0)
Status: In Progress
Phases: 2 of 6 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 14 | Setup Page | 1 | Complete | 2026-04-02 |
| 15 | Build Tab Polish | 1 | Complete | 2026-04-03 |
| 16 | Build — Save & Use RAG Config | TBD | Not started | - |
| 17 | Test Tab Fixes | TBD | Not started | - |
| 18 | Experiment Runner | TBD | Not started | - |
| 19 | Analyze Fixes | TBD | Not started | - |

## Phase Details

### Phase 14: Setup Page

**Goal:** Build the Setup page with API endpoint connection for external bot evaluation, and CSV upload for importing Q&A pairs with sources for judging against the RAG bot.
**Depends on:** v0.2 complete (existing app shell)
**Research:** Unlikely

**Scope:**
- Replace placeholder StagePlaceholder with real Setup content
- API endpoint configuration (connect to external service for relevance info)
- CSV upload for external bot questions, answers, and sources
- Validation and preview of imported data
- Integration with downstream stages (data available for experiments)

**Plans:**
- [ ] TBD during /paul:plan

### Phase 15: Build Tab Polish

**Goal:** Fix PDF reading, add help/documentation links for all config fields, and fix the delete confirmation button.
**Depends on:** Phase 14 (or can run independently)
**Research:** Unlikely

**Scope:**
- Fix PDF file reading issue (backend has pypdf support, diagnose frontend/dependency gap)
- Add help text / tooltips / documentation links for each config field name and option
- Fix "Yes" delete confirmation button not working
- Improve UX clarity across all Build sub-panels

**Plans:**
- [ ] TBD during /paul:plan

### Phase 16: Build — Save & Use RAG Config

**Goal:** Allow saving a complete RAG configuration (chunking + embedding + RAG as one unit) that can be selected in the Experiment phase.
**Depends on:** Phase 15 (build tab working correctly)
**Research:** Unlikely

**Scope:**
- "Save full config" action that bundles chunk config + embedding config + RAG config
- Saved config selectable when creating experiments
- Config summary display showing all component settings

**Plans:**
- [ ] TBD during /paul:plan

### Phase 17: Test Tab Fixes

**Goal:** Enable custom persona editing and fix color scheme issues (white boxes).
**Depends on:** v0.2 complete
**Research:** Unlikely

**Scope:**
- Custom persona editor (name, description, traits — not just toggle + count)
- Fix white background boxes to match dark theme color scheme
- Ensure all test tab elements follow design system tokens

**Plans:**
- [ ] TBD during /paul:plan

### Phase 18: Experiment Runner

**Goal:** Ensure experiments actually test the RAG bot against test questions end-to-end.
**Depends on:** Phase 16 (saved RAG configs), Phase 17 (working test sets)
**Research:** May need debugging

**Scope:**
- Verify experiment runner queries RAG bot per approved question
- Diagnose and fix any wiring issues preventing end-to-end execution
- Ensure results are stored and displayed correctly
- Error handling and recovery for failed runs

**Plans:**
- [ ] TBD during /paul:plan

### Phase 19: Analyze Fixes

**Goal:** Fix generate suggestion button and apply suggestion flow.
**Depends on:** Phase 18 (completed experiments needed)
**Research:** Unlikely

**Scope:**
- Fix response type mismatch between backend and frontend for suggestion generation
- Fix apply suggestion flow (backend returns different structure than frontend expects)
- Verify full analyze workflow: generate → view → apply → iterate

**Plans:**
- [ ] TBD during /paul:plan

### Phase 9: Foundation & Design System

**Goal:** React+Vite+Tailwind app scaffold with design system, layout shell, project selector, and routing.
**Depends on:** v0.1 complete (existing backend API)
**Research:** Unlikely (standard React+Vite+Tailwind setup)

**Scope:**
- React + Vite project setup with TypeScript
- Tailwind CSS with dark theme tokens (carry forward dashboard aesthetic)
- Shared component library (buttons, cards, inputs, badges, toasts, modals)
- Layout shell: sidebar with stepper navigation (Setup → Build → Test → Experiment → Analyze)
- Project selector (create/switch projects)
- React Router with route guards (project must be selected)
- FastAPI static file serving for the React build

**Plans:**
- [ ] TBD during /paul:plan

### Phase 10: Document & RAG Pipeline

**Goal:** Upload documents, configure chunking & embedding, and set up RAG bot — all in the Build stage of the workspace.
**Depends on:** Phase 9 (app shell and components)
**Research:** Unlikely (wiring existing API endpoints to React components)

**Scope:**
- Document upload UI (drag-and-drop, PDF/TXT, file list with status)
- Chunking configuration (strategy selector, parameter tuning, chunk preview)
- Embedding configuration (model selector, vector store config)
- RAG bot setup (response mode, retrieval parameters)
- Pipeline status indicators (which steps are configured)

**Plans:**
- [ ] TBD during /paul:plan

### Phase 11: Test Generation & Annotation

**Goal:** Generate test sets and annotate questions — the Test stage of the workspace.
**Depends on:** Phase 10 (documents and RAG config must exist)
**Research:** Unlikely (existing endpoints, new UI)

**Scope:**
- Test set generation UI (persona config, query distribution, generation trigger)
- Annotation workflow (approve/reject/edit inline, bulk actions, progress tracking)
- Status badges and filtering (pending/approved/rejected/edited)
- Test set management (list, select, view stats)

**Plans:**
- [ ] TBD during /paul:plan

### Phase 12: Experiments & Results

**Goal:** Configure experiments, run with live progress, view results and comparisons — the Experiment and Analyze stages.
**Depends on:** Phase 11 (approved test sets needed)
**Research:** Unlikely (SSE streaming in React, existing endpoints)

**Scope:**
- Experiment creation (model, RAG config, test set, metrics selection)
- SSE-based experiment runner with live progress
- Results dashboard (per-question scores, aggregate metrics, response text)
- Side-by-side experiment comparison with delta visualization
- Metric visualization (score bars, charts)
- Historical experiment timeline

**Plans:**
- [ ] TBD during /paul:plan

### Phase 13: Feedback Loop & Polish

**Goal:** Complete the iteration workflow and polish the app for release. Remove old HTML pages.
**Depends on:** Phase 12 (results and suggestions to act on)
**Research:** Unlikely (UI polish and cleanup)

**Scope:**
- Improvement suggestions display with Apply buttons
- Delta comparison view for iteration experiments
- CSV/JSON export
- Stepper completion indicators (visual progress across pipeline stages)
- Responsive design polish
- Remove old vanilla HTML pages (index, testgen, annotation, experiments, dashboard)
- Update FastAPI routing to serve React app

**Plans:**
- [ ] TBD during /paul:plan

---
*Roadmap created: 2026-03-31*
*Last updated: 2026-04-03 — Phase 15 complete*
