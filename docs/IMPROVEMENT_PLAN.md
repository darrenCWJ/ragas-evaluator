# Tribunal (RAG Evaluator) — Full Critique & Improvement Plan

> Generated 2026-06-12 from a complete audit of every layer: backend routes, DB layer,
> evaluation engine, RAG pipeline, worker service, React frontend, tests, CI, config,
> deployment, and docs. This is the working plan for the v0.4+ overhaul.

## Execution status (updated 2026-06-13 — verified against code, not memory)

> **Session handoff notes (read first in a fresh session):**
> - All work lives on branch **`feat/v0.4-overhaul`**, fully pushed — **PR #54**
>   (github.com/darrenCWJ/tribunal). `origin/main` has NONE of it until the PR merges.
>   Local `main` == the PR branch.
> - Python env: the repo `.venv` was corrupted by OneDrive — use
>   **`C:\venvs\ragas-eval\Scripts\python.exe`** (all deps + ruff installed).
> - Verify loop: `ruff check .` → `pytest tests/unit -q` (needs env
>   `OPENAI_API_KEY=sk-dummy`; integration tests run with mocked LLMs) → from
>   `frontend/`: `npx tsc --noEmit && npm run build && npx eslint src`.
> - A `langchain_community.chat_models.vertexai` stub is needed to import ragas
>   outside pytest — copy the pattern from `tests/conftest.py`.
> - Known pre-existing quirk: eslint has 77 warnings baseline (react-hooks v7
>   compiler rules at 'warn'); 0 errors is the gate.

| Phase | Status | Commits |
|---|---|---|
| 0 — Repo hygiene & tooling (ruff/eslint/prettier + CI, broken Dockerfile.dev, path anchoring, naming) | ✅ Done | `adc2c069` |
| 1 — Critical correctness (ProgressStore, LLM retry/backoff, SSE hardening, query bounds, event-loop unblocking) | ✅ Done | `c58b255e` |
| 2 — Backend restructure: worker fork DELETED (worker imports root modules; Docker builds from repo root), ghost features closed (instance_rubrics, Glean-as-LLM, token tracking) | ✅ Done | `a809dd2e` |
| 2.5 — Memory & storage: KG zlib compression (~25x), RLIMIT_AS subprocess cap, /api/system/maintenance, per-batch KG checkpoints + gc/malloc_trim | ✅ Done | `6ad82c34` |
| 3 — Frontend restructure: api.ts → 15 domain modules, 12 ui/ primitives, useFetch/usePolling/useConfirm/useSSE hooks, ErrorBoundary, god-component splits (TestSetGenerate → generate/, ExperimentRunner → runner/) | ✅ Done | `0b29eb13`, `a5d705e2`, `25ca083b` |
| 4 — Tests & CI: mocked-LLM pattern, strict markers, route tests for ALL legacy modules (testsets/analyze/personas/custom_metrics/auth/conversation) — 36 backend test files | ✅ Done (backend) / ❌ frontend has zero tests (no Vitest) | `9d9a7687` + feature commits |
| 5 — Skill Arena: skill file × model matrix, adherence/format/lift metrics, step traces + optional Langfuse export, apply-winner | ✅ Done | `b2181249`, `d61a79d7` |
| 6 — Docs: README/FEATURES/WORKFLOW refreshed, all CODEMAPS regenerated from code | ✅ Done | `0bb17eeb`, `349201fe` |
| 7 — Test set transparency: quality audit (deterministic + LLM), provenance (source_chunk_ids), coverage report, refusal_accuracy metric, category breakdown; external (uploaded) test sets fully supported incl. category column + refusal tagging | ✅ Done | `76ea0bb9`, `7e6d7588` |
| 8 — Suggestion engine v2: guardrail snippet library (grounding/refusal/noise/persona/phases), category-gap rules, system_prompt_append apply mode, Prompt Doctor (LLM drafts revised prompt from worst failures) | ✅ Done | `ab4b1866` |
| 9 — Improvement loop closed: retrieval_hit_rate/retrieval_mrr (deterministic, via provenance), bootstrap CIs on aggregates, suggestion outcomes (paired verdicts: improved/regressed/inconclusive), outcome badges + CI display in UI | ✅ Done | `5dc3bec3`, `b96ff953` |
| 10 — UX: Start guide page (two paths: external agent vs internal RAG, live step progress), grouped metric selection with descriptions/cost tags/presets, shareable standalone HTML report | ✅ Done | `fed51794`, `6d823209` |
| 11 — Multi-turn conversation testing + CI quality gate endpoint | ✅ Done | `135eef03`, `9d9a7687`, `25ca083b` |
| 12 — Auth: multi-user logins, admin role (sees all projects), project isolation, machine token | ✅ Done | `466da7a6` |

### Remaining work (updated 2026-06-12 session, priority order)

**Engineering debt**
1. ~~**Frontend unit tests**~~ ✅ Done — Vitest + RTL wired into vite.config.ts; 46 tests:
   api/client error paths, useFetch/usePolling hooks, 22 page smoke tests (all 11 pages
   × no-project + project-with-API-down). `npm test` added to CI frontend job.
2. ~~**Extract `app/services/experiment_runner.py`**~~ ✅ Done — `_run_background` (~700 LOC)
   moved to `run_experiment_background()` plus public helpers (`sanitize_nan`,
   `parse_experiment_row`, `compute_aggregates`, `aggregate_rows`, `compute_token_usage`,
   `retrieval_diagnostics`, `build_virtual_rag_config_row`). Routes file 2,480 → ~1,640 LOC.
   analyze/annotations/reports now import from the service; test patch targets updated.
3. ~~**Request-ID logging middleware**~~ ✅ Done — `app/services/request_context.py`
   (ContextVar + RequestIDMiddleware outermost + RequestIDFilter); log format carries
   `[request_id]`; X-Request-ID honored/echoed; background tasks inherit the id via
   contextvars. 8 unit tests.
4. Check whether eslint `react-hooks/set-state-in-effect`/`react-hooks/refs` can now ratchet from 'warn' back to 'error' (god splits landed; remaining warners are legacy pages — 71 warnings as of this session).

**Retrieval upgrades**
5. ~~**Small-to-big retrieval**~~ ✅ Done — NOTE: the original premise was wrong;
   `_parent_child` discarded parents entirely (parent_chunk_id was never populated).
   Implemented via metadata: `parent_child_pairs()` in chunking, generation stores
   `parent_key`/`parent_content` on child rows (`metadata_json`), and
   `_expand_to_parents()` in `pipeline/rag.py` swaps child hits for parent windows
   post-retrieval (sibling + cross-step dedupe; child chunk_id kept for provenance).
   ⚠️ Existing parent_child chunk sets must be re-generated (force=true) to gain
   parent metadata; old sets pass through unchanged.
6. **Query expansion (multi-query + RRF reuse) / HyDE** as experimentable `rag_configs` fields.
7. **Score-threshold cutoff + MMR diversity** post-filters instead of blind top_k.
8. `text-embedding-3-large` option + `BAAI/bge-reranker-v2-m3` reranker option.
9. KG-assisted retrieval (vector hits → 1-hop KG expansion → rerank) — biggest differentiator, do after 5–7.

**Evaluation/product features (recommended, not built)**
10. **Parameter sweep experiments** — grid over top_k/alpha/chunk configs, auto-spawn experiments, leaderboard; run judge-free first using retrieval_hit_rate, judge the top finalists.
11. **Judge calibration** — human annotation data (20% samples) is collected but unused; pick default judge per project by human agreement.
12. **Scheduled regression runs** against external agents with alerts on metric drops.
13. Real-user log import → test questions; hard-case mining (auto-generate variants of failed questions).

**Known quirks to be aware of**
- `tests/integration/test_glean_experiment.py::test_glean_all_metrics` (slow marker) fails
  in any env without ANTHROPIC_API_KEY + GOOGLE_API_KEY: it runs ALL 26 metrics incl.
  multi_llm_judge, whose pre-run judge validation requires all three provider keys.
  Pre-existing (fails identically on the pre-refactor baseline); not run in CI.
- Slow integration tests need the real OPENAI_API_KEY from `.env` — do NOT export
  OPENAI_API_KEY=sk-dummy when running them (that's for `tests/unit` only).
- Windows: `core.autocrlf=true` checkouts are CRLF; prettier is configured with
  `endOfLine: "auto"` so format:check passes locally and in CI.
- Worker delegation for experiments/testgen posts to `/run-experiment`/`/run-testgen` endpoints the worker does NOT implement — silently falls back to local execution (documented in CODEMAPS/worker.md limitations).
- `resource` module usage in worker /status is Unix-only (fine in Docker, N/A on Windows dev).
- Coverage report legitimately shows "doesn't apply" for corpus-less projects (external agent + uploaded test set).

---

## Part 1 — Critique of the Current Program

### 1.1 The big picture

The app works, but it grew by accretion: features were bolted onto a few files until
they became unmanageable. The five worst offenders hold ~40% of all hand-written code:

| File | Size | What it actually is |
|---|---|---|
| `app/routes/experiments.py` | 2,316 LOC | Routes + SSE streaming + background task manager + worker delegation + aggregation, all in one |
| `app/routes/testsets.py` | 2,061 LOC | Routes + generation orchestration + KG subprocess manager + progress tracking |
| `evaluation/metrics/testgen.py` | 2,696 LOC | KG build + personas + 5 question synthesizers + dedup + orchestration |
| `frontend/src/components/test/TestSetGenerate.tsx` | 1,815 LOC, 22 useState | Persona gen + KG build polling + distribution sliders + form, one component |
| `frontend/src/lib/api.ts` | 2,327 LOC | 100+ interfaces and 150+ flat fetch functions in a single file |

This is the primary "AI slop" symptom: every change touches a god-file, debugging means
scrolling thousands of lines, and the same patterns (progress dicts, error banners,
fetch-then-setState) are re-implemented inline dozens of times instead of extracted once.

### 1.2 Critical defects (fix before anything else)

1. **Worker tree is a stale copy-paste fork.** `worker/db/init.py`, `worker/config.py`,
   and `worker/evaluation/metrics/testgen.py` are near-duplicates of the main modules
   that have **drifted in both directions**:
   - Worker `db/init.py` is missing the PostgreSQL `%` LIKE-escaping fix (main `db/init.py:64-65`)
     → corrupted LIKE queries on Postgres.
   - Worker `db/init.py` is missing the `knowledge_graphs` UNIQUE-constraint migration
     (main `db/init.py:490-505`) → duplicate KG rows in production.
   - Worker `testgen.py` has memory-profiling/`gc` hardening (`_log_memory`, `_release_memory`)
     that the main copy lacks → different memory behavior for the same build depending on
     where it runs.
2. **Data races on module-level dicts.** `_experiment_progress` is written by async
   background tasks and read by the SSE generator with no lock
   (`experiments.py:934,1074,1478,1502,1513,1521,1727`); `.pop()` calls at
   `experiments.py:1722,1865` bypass `_experiment_worker_lock` entirely.
3. **No retry/backoff anywhere on LLM calls.** `pipeline/llm.py` clients use
   `max_retries=1`; `evaluation/scoring.py:_score_builtin` returns `None` on first
   failure. A transient 429 silently nulls a metric mid-experiment and burns the rest of
   the run's API spend.
4. **No checkpointing in test generation.** `generate_test_set()` is a ~300-line
   all-or-nothing orchestrator; an interrupt at question 900/1000 loses everything.
5. **Zero frontend tests; 4 backend route modules fully untested** (`testsets` 2,061 LOC,
   `analyze` 561, `personas` 398, `custom_metrics` 198). Integration tests need a real
   OpenAI key, so CI never runs them. 80% of tests carry no pytest marker.

### 1.3 High-severity defects

- **Unbounded queries**: list endpoints (`experiments.py:400`, `bot_configs.py:96`,
  `rag.py:62`, `embeddings.py:57`) `fetchall()` with no LIMIT; the compare endpoint loads
  everything *before* its 2,500-row guard (`experiments.py:563-574`).
- **Swallowed exceptions**: `except Exception: pass` in SSE/polling/aggregation paths
  (`experiments.py:1598`, `testsets.py:720,857`, `analyze.py:347`) — the exact paths that
  are hardest to debug get no logging.
- **Blocking calls in async context**: ChromaDB `query()` (`pipeline/vectorstore.py`) and
  the cross-encoder reranker run synchronously on the event loop → SSE stalls.
- **Connection lifecycle**: background-task DB connections rely on a single `finally`
  (`experiments.py:1554`); error paths can leak connections.
- **`Dockerfile.dev` is broken** — it runs `npx next dev`, but this is a Vite app.
- **Dependency drift**: worker pins `fastapi>=0.136.1` / `openai>=2.32.0` vs main's
  `>=0.115.0` / `>=2.29.0`; only lower bounds anywhere; no lock file; the
  `langchain_community.chat_models.vertexai` shim is duplicated in `main.py` and
  `tests/conftest.py` and will break on the next ragas/langchain bump.
- **Frontend robustness**: no error boundary anywhere; polling loops without
  AbortController cleanup (TestSetGenerate, WorkersPage); generation-progress polling
  ignores all errors (`TestSetGenerate.tsx:302-304`); ~60 LOC duplicated verbatim between
  `handleRun` and the auto-reconnect path in ExperimentRunner; type hacks like
  `null as unknown as Experiment` (`ExperimentList.tsx:124`).

### 1.4 Incomplete / not-yet-available features (current state)

| Feature | State | Evidence |
|---|---|---|
| `instance_rubrics` metric | Selectable in UI, **always returns None** | `evaluation/scoring.py:333` "per-question rubrics not yet supported in runner" |
| Glean as LLM provider | Raises **501 Not Implemented** | `pipeline/llm.py:137-138` (Glean works only as a bot connector) |
| Partial / resumable test generation | Not available | `generate_test_set()` has no stage checkpoints |
| Workers page task clearing | Only persona + KG tasks clear; experiment/testgen buttons no-op | `WorkersPage.tsx:108-111` |
| Cost / token tracking | Not available anywhere | no token counting in `pipeline/llm.py` or scoring |
| Pagination | Not available on any list endpoint | all routes `fetchall()` |
| System-prompt / skill-file injection for bot connectors | Not available | `BotConnector.query(question)` takes only a question — this is what the new feature needs |

### 1.5 Hygiene & docs

- ~8.7 MB of junk committed: `graphify-out/` (3.3 MB), `demo/demo-ragas.webm` (5.5 MB),
  `.playwright-mcp/` (1.9 MB) — all listed in `.gitignore` but added before the rules.
- Stray `data;C/` directory (Windows artifact), empty `ragas_test.db`, seed scripts at root.
- Naming split: repo is "ragas-evaluator", README says "Tribunal", remote is `tribunal`.
- CLAUDE.md says 14 route modules (there are 16); `.env.example` documents ~85 vars while
  `config.py` reads 36; `.gitlab-ci.yml` is permanently disabled dead weight.
- No linter or formatter exists in the repo at all (no ruff/black/eslint/prettier).

### 1.6 What's actually good (keep these)

- SSRF protection in `bot_connectors/custom.py` is genuinely strong (private-IP blocks,
  DNS-rebinding check, `ALLOW_PRIVATE_ENDPOINTS` escape hatch).
- All SQL is parameterized; upload validation (extension + size) is correct.
- The bot-connector factory pattern is clean and extensible — it's the right foundation
  for the new skill-testing feature.
- Glean connector's retry/backoff is the model the other connectors should copy.
- Metric registry (one async function per file, dispatched from `scoring.py`) is a good
  pattern; it just needs retries and the instance_rubrics gap closed.
- Dual SQLite/Postgres backend with the `_PgConnection` shim works.

---

## Part 2 — Target Architecture

### 2.1 Backend folder structure

The rule: **routes do HTTP only**. Business logic moves to a `services/` layer, shared
state gets real managers, and the worker imports from a shared package instead of
carrying forks.

```
app/
├── __init__.py              # factory, middleware, lifespan (unchanged role)
├── models/                  # split models.py by domain
│   ├── projects.py, experiments.py, testsets.py, metrics.py, ...
├── routes/                  # thin HTTP handlers only (<300 LOC each)
│   ├── experiments.py       # parse request → call service → shape response
│   └── ...
├── services/                # NEW — extracted business logic
│   ├── experiment_runner.py # run loop, cancellation, aggregation
│   ├── experiment_progress.py # ProgressStore class (lock-guarded, TTL-evicted)
│   ├── testgen_service.py   # generation orchestration, checkpoint/resume
│   ├── kg_builds.py         # subprocess/thread KG build management
│   ├── worker_client.py     # all worker HTTP delegation + circuit breaker
│   └── suggestions_service.py
├── sse.py                   # NEW — shared SSE event helpers (heartbeat, error frames, timeout)
core/                        # NEW shared package (replaces copy-paste worker fork)
├── config.py                # single config; worker imports the subset it needs
├── db/
│   ├── schema.py            # tables + migrations (one source of truth)
│   ├── connection.py        # context-managed connections, thread-local pool
│   └── queries/             # per-domain query modules (experiments.py, testsets.py, ...)
├── llm/
│   ├── client.py            # multi-provider routing + retry/backoff + token counting
│   └── budget.py            # cost tracking per experiment
└── testgen/                 # split the 2,696-line testgen module
    ├── kg_build.py, personas.py, single_hop.py, multi_hop.py,
    ├── graph_rag.py, dedup.py, checkpoints.py, orchestrator.py
worker/
├── main.py, routes.py       # stays, but imports core.* — no more forked copies
```

### 2.2 Frontend folder structure

```
frontend/src/
├── api/                     # split api.ts: client.ts (request/formRequest/SSE) +
│   ├── projects.ts, documents.ts, chunks.ts, embeddings.ts, rag.ts,
│   ├── testsets.ts, experiments.ts, annotations.ts, metrics.ts, kg.ts,
│   ├── workers.ts, skills.ts (new), types/ (interfaces per domain)
├── components/
│   ├── ui/                  # grow from 2 → ~12 primitives:
│   │   # TextInput, Select, FormField, Button, Spinner, ErrorAlert,
│   │   # ConfirmDelete, Modal, ScoreBar, Badge, EmptyState, ProgressBar
│   ├── build/ test/ experiment/ kg/ setup/ skills/ (new)
├── hooks/                   # NEW
│   ├── useFetch.ts          # fetch+loading+error+abort in one hook
│   ├── usePolling.ts        # interval polling with cleanup + error surfacing
│   ├── useSSE.ts            # SSE-over-POST stream with reconnect (extracted from ExperimentRunner)
│   └── useConfirmDelete.ts
├── pages/                   # one folder per page when a page has subcomponents
└── lib/                     # scoreUtils etc.
```

God components split: `TestSetGenerate` → `PersonaSection` + `KGBuildStatus` +
`DistributionForm` + `GenerateForm` (+ `useGenerationProgress` hook); `ExperimentRunner` →
`RunControls` + `RubricsForm` + `JudgeSlots` + `RunLog` (+ `useSSE`); `KGGraphView` →
`GraphCanvas` + `KGFilters` + `useKGLayout`; `CustomMetricBuilder` → per-type form
subcomponents.

---

## Part 3 — Phased Improvement Plan

Each phase ends green: tests pass, frontend builds, app boots. Order matters — hygiene
and safety nets come before restructuring, restructuring before the new feature.

### Phase 0 — Repo hygiene & tooling (½ day)

- [ ] `git rm -r --cached graphify-out .playwright-mcp demo/demo-ragas.webm`; verify `.gitignore` covers them; delete `data;C/`, `ragas_test.db`, `.gitlab-ci.yml`.
- [ ] Move `seed_mock_data.py`, `seed_results.py` → `scripts/`.
- [ ] Pick one name (Tribunal or RAG Evaluator) and apply it everywhere.
- [ ] Add **ruff** (lint + format) with `pyproject.toml`; add **eslint + prettier** to frontend; wire both into `ci.yml` alongside the existing pytest/tsc steps.
- [ ] Add `requirements.lock` (pip-compile) for app and worker; align worker pins with main.
- [ ] Fix `Dockerfile.dev` (`npx next dev` → `npm run dev` with Vite).
- [ ] Make `DATABASE_PATH` resolve relative to the repo root, not CWD.
- [ ] Prune `.env.example` to the vars `config.py` actually reads; fix CLAUDE.md route count.

### Phase 1 — Critical correctness fixes (1–2 days, no restructuring yet)

- [ ] **Worker DB sync**: port the `%` LIKE-escape fix and the `knowledge_graphs` UNIQUE migration into `worker/db/init.py` (stopgap before Phase 2 deduplication).
- [ ] **Lock the progress state**: introduce a `ProgressStore` class wrapping `_experiment_progress` + `_cancel_events` + `_experiment_worker` with one `threading.RLock`, TTL eviction for dead entries; replace all raw dict access in `experiments.py` and `testsets.py`.
- [ ] **LLM retry/backoff**: central `with_backoff()` (exponential + jitter, honors `Retry-After`) in `pipeline/llm.py`; apply to chat, embeddings, and `_score_builtin`; raise client `max_retries` to 3. Copy the Glean connector's pattern to OpenAI/Claude/DeepSeek/Gemini connectors and enforce `BOT_QUERY_TIMEOUT` everywhere.
- [ ] **Stop swallowing errors**: every `except Exception: pass` gets `logger.exception(...)` minimum; SSE generators emit a structured `{"event":"error","detail":...,"recoverable":bool}` frame before closing; add heartbeat + hard timeout (`asyncio.wait_for`) to the `while True` SSE loops.
- [ ] **Bound the queries**: `LIMIT`/`offset` params on all list endpoints (default limit 200); move the compare-endpoint guard into the SQL (`LIMIT 2501`).
- [ ] **Connection safety**: context-manager (`with get_conn() as conn:`) for all background-task DB use.
- [ ] **Unblock the event loop**: wrap ChromaDB queries and reranker scoring in `asyncio.to_thread`.
- [ ] Quick frontend safety: add a top-level `ErrorBoundary`; add AbortController cleanup to the polling loops; surface polling errors in TestSetGenerate instead of `catch {}`.

### Phase 2 — Backend restructure (3–5 days)

- [ ] Create `core/` package: move `config.py`, split `db/init.py` into `schema.py` + `connection.py` + `queries/` modules. **Delete `worker/db`, `worker/config.py`, `worker/evaluation` — worker imports `core.*`.** Keep the worker's memory-hardening helpers (move them into `core/testgen/kg_build.py` so both sides get them).
- [ ] Split `evaluation/metrics/testgen.py` into `core/testgen/` modules (kg_build, personas, single_hop, multi_hop, graph_rag, dedup, orchestrator) with **stage checkpoints** persisted to DB so generation can resume.
- [ ] Extract `app/services/` from the route god-files: `experiments.py` route module shrinks to HTTP handling; runner loop, aggregation (`_compute_aggregates`/`_aggregate_rows` merged into one), worker delegation (single `worker_client.py` with circuit breaker) and status updates (one `update_experiment_status()`) each live once.
- [ ] Split `app/models.py` by domain.
- [ ] Close the known feature gaps while the code is open:
  - [ ] `instance_rubrics`: load per-question rubrics from test-set metadata and wire into the runner (or remove it from the selectable metric list — no silent None).
  - [ ] Glean-as-LLM: route `glean-*` models through the Glean bot connector or remove the option.
  - [ ] Workers page: implement clear/cancel for experiment + testgen task types.
  - [ ] Token/cost tracking: count tokens per LLM call in `core/llm/client.py`, aggregate per experiment, expose in results API.

### Phase 3 — Frontend restructure (3–5 days)

- [ ] Split `lib/api.ts` → `api/` domain modules + shared `client.ts` (single error-extraction path, typed `ApiError`).
- [ ] Build the `ui/` primitive set (TextInput, FormField, Select, Button, Spinner, ErrorAlert, ConfirmDelete, Modal, ScoreBar, Badge, EmptyState, ProgressBar) and sweep the codebase to replace the 82 inline input clones, 15 error banners, 10 spinners, 4 confirm-delete patterns.
- [ ] Extract `hooks/`: `useFetch`, `usePolling` (with abort + error surfacing), `useSSE` (deduplicates ExperimentRunner's 60-line reconnect copy), `useConfirmDelete`.
- [ ] Split the god components (see §2.2). Target: no component over 400 LOC, no component over 8 useState.
- [ ] Remove type hacks (`null as unknown as Experiment` → proper `Experiment | null` state) and `as` casts behind real type guards.

### Phase 4 — Test & CI hardening (2–3 days, interleave with 2–3)

- [ ] Backend: add route tests for the four untested modules (testsets, analyze, personas, custom_metrics) using FastAPI TestClient + a fake LLM layer (`core/llm` gets an injectable transport so integration tests never need real keys).
- [ ] Add concurrency tests: SSE stream while progress updates, cancel mid-run, worker death mid-delegation.
- [ ] Add `pytest.ini` `addopts = --strict-markers`; mark every test; CI runs unit on PR, integration (fake-LLM) nightly.
- [ ] Frontend: Vitest + React Testing Library; smoke tests for api client error paths, hooks (usePolling abort behavior, useSSE reconnect), and one render test per page.
- [ ] CI: ruff + eslint + tsc + pytest + vitest + build; coverage gate starting at current baseline, ratcheting up.
- [ ] Consolidate the langchain vertexai shim into one module (`core/compat.py`) imported by both entrypoints and conftest.

### Phase 5 — NEW FEATURE: Skill Arena (multi-AI skill-file testing) (4–6 days)

See Part 4 for the full spec.

### Phase 6 — Polish & docs (1–2 days)

- [ ] Regenerate docs/CODEMAPS; rewrite README structure section to match the new layout; document the Skill Arena workflow in docs/FEATURES.md.
- [ ] Add structured logging (request-id middleware, per-experiment log context) — this plus the de-godfiling is what makes the app "easier to debug".
- [ ] Optional: OpenTelemetry-style timing spans around LLM calls, retrieval, scoring, surfaced in the experiment detail view.

---

## Part 4 — New Feature Spec: Skill Arena

**Goal:** test how a *skill file* (SKILL.md-style instruction/system document) performs
across different AI models — does each model follow it, how well, and at what cost?

### 4.1 Concept

A **Skill** is a markdown/text instruction document. A **Skill Trial** runs a matrix:

```
(skill file or no-skill baseline) × (target AI: any bot connector) × (test set questions)
```

Each cell sends the skill as system context + the question to the model, captures the
response, and scores it on adherence and quality. Results render as a model × skill
matrix with drill-down, directly answering "which AI follows my skill file best?"

### 4.2 Why the current architecture almost supports this

- Bot connectors already normalize OpenAI / Claude / DeepSeek / Gemini / custom HTTP to
  one interface — but `BotConnector.query(question)` cannot carry a system prompt today
  (confirmed gap, `pipeline/bot_connectors/base.py`). That's the one interface change.
- The experiment runner, SSE progress, metrics dispatch, and comparison UI are all
  reusable as-is once a trial is modeled as a batch of experiments.

### 4.3 Backend design

```
core/skills/
├── parser.py        # parse SKILL.md: frontmatter (name, description, triggers),
│                    # body, extract testable directives ("always X", "never Y",
│                    # output-format rules) via LLM into a structured checklist
└── adherence.py     # scoring helpers

app/routes/skills.py         # CRUD: upload/list/version skill files per project
app/routes/skill_trials.py   # create/run/compare trials (SSE progress, reuses runner)
app/services/skill_trial_runner.py
evaluation/metrics/skill_adherence.py   # NEW metrics (below)
```

**Schema** (added via the normal migration path in `core/db/schema.py`):

```sql
skills        (id, project_id, name, version, content, parsed_directives_json, created_at)
skill_trials  (id, project_id, skill_id NULLABLE, name, test_set_id, models_json,
               include_baseline BOOL, status, created_at)
skill_trial_results (id, trial_id, skill_id NULLABLE, model, question_id,
               response, scores_json, tokens_in, tokens_out, latency_ms, error)
```

**Connector change** — extend the base interface (backward compatible):

```python
class BotConnector(Protocol):
    async def query(self, question: str, *, system_context: str | None = None) -> BotResponse: ...
```

- OpenAI/DeepSeek/custom: prepend as `system` message.
- Claude: `system=` parameter.
- Gemini: `system_instruction`.
- CSV/Glean: reject with a clear error ("connector does not support system context").

### 4.4 New metrics

| Metric | How it works |
|---|---|
| `skill_adherence` | LLM judge scores the response against the parsed directive checklist (per-directive pass/fail → ratio). Reuses the multi-LLM-judge machinery for reliability. |
| `format_compliance` | Deterministic checks where possible (response matches output format rules extracted from the skill: JSON shape, headings, length caps). |
| `instruction_retention` | For multi-turn trials (v2): does adherence decay over turns? |
| `skill_lift` | Delta vs the no-skill baseline cell on the same question/model — the headline number. |
| Cost columns | tokens_in/out + latency per cell, from the Phase-2 token tracking. |

### 4.5 Frontend

```
pages/SkillsPage.tsx                  # new stepper entry: "Skills"
components/skills/
├── SkillUpload.tsx        # upload/paste SKILL.md, preview parsed directives, versions
├── SkillTrialCreate.tsx   # pick skill(s), models (from bot configs), test set,
│                          # baseline toggle, metric selection
├── SkillTrialRunner.tsx   # reuses useSSE hook for live matrix-fill progress
├── SkillMatrix.tsx        # heatmap: rows=models, cols=skills(+baseline),
│                          # cells=adherence score, click → drill-down
└── SkillTrialDetail.tsx   # per-question: response side-by-side across models,
                           # directive checklist with pass/fail, judge reasoning
```

### 4.6 Build order (within Phase 5)

1. Connector `system_context` support + tests (unblocks everything; also independently useful).
2. Skill CRUD + parser (directive extraction prompt + golden-file tests).
3. Trial runner service reusing experiment-runner internals + SSE.
4. `skill_adherence` + `format_compliance` metrics with golden fixtures.
5. UI: upload → create trial → matrix → drill-down.
6. Baseline/lift computation + CSV/JSON export.

### 4.7 Acceptance criteria

- Upload a SKILL.md, run a trial across ≥3 providers + baseline on a 20-question set,
  watch live progress, and read a matrix that ranks models by adherence with per-question
  evidence — without code changes or restarts.
- A failed cell (rate limit, timeout) retries with backoff, then records an error state
  visible in the matrix; the trial completes.
- Re-running an identical trial costs ~0 extra design work (idempotent trial naming + versioned skills).

---

## Part 5 — Risks & Verification

| Risk | Mitigation |
|---|---|
| Restructure breaks worker deployment | Phase 1 syncs worker DB first; Phase 2 keeps worker HTTP API identical; integration test hits worker routes with fake LLM |
| api.ts split breaks imports en masse | Barrel re-export (`lib/api.ts` re-exports from `api/`) during migration, removed at the end |
| ragas/langchain version bumps | Lock files + the consolidated compat shim + CI nightly with unpinned resolve to detect breakage early |
| Cost of skill trials (N models × M questions) | Token budget preview before run ("est. X calls / ~Y tokens"), per-trial cap from config |
| Big-bang refactor stalls | Every phase independently shippable; god-files are split one at a time behind unchanged route signatures |

**Definition of done per phase:** ruff/eslint clean, `pytest` green, `tsc && vite build`
green, app boots, one manual end-to-end pass of the affected workflow.

**Estimated total:** ~15–22 working days (phases 2–4 partially parallelizable).
