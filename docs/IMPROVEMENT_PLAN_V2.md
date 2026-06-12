# Tribunal — Improvement Plan v2

> Created 2026-06-12 from a parallel-agent audit of the current codebase (post v0.4
> overhaul / PR #54). Covers 7 improvement areas requested by the user:
> agentic tool calling, worker nodes + feedback fixes, guide page, Tribunal rename,
> test-type compatibility gating, more file types + images, and skills v2
> (multi-file / progressive disclosure / user input).
>
> ## ✅ ALL PHASES COMPLETE — 2026-06-12
>
> P1–P7 implemented on branch `feat/v2-improvements` (7 commits, one per phase),
> verified green: ruff, 611 backend tests (unit + non-slow integration),
> 48 frontend Vitest tests, tsc, eslint (0 errors), production build.
>
> Notes vs the original plan:
> - The audit's "human annotation has no UI" finding (2.4) was wrong — the panel
>   was already mounted on AnalyzePage; the real fixes were the six missing worker
>   endpoints, the RAM bug, the reliability verdict-count inflation, and a stale
>   closure in MultiLLMJudgePanel.
> - tool_call_accuracy stayed "coming soon"; tool_call_f1 ships as a deterministic
>   trace-vs-reference metric instead of the ragas wrapper (no LLM cost).
> - Run-route capability validation: explicit metric requests 422 on missing
>   capabilities; the default fallback metric set is filtered instead.
> - 6.3 (vision pass for image-only PDF pages) deliberately deferred.
>
> Status legend: ☐ not started · ◐ in progress · ✅ done (phase headers below
> kept as the original plan for reference)

---

## Executive summary

| # | Area | Effort | Key finding from audit |
|---|------|--------|------------------------|
| 1 | Agentic tool calling | L | No `tools=` param anywhere; `pipeline/llm.py:chat_completion()` is the single choke point; ragas tool metrics already vendored but marked "Coming Soon" in UI |
| 2 | Worker nodes + feedback | M | **Confirmed RAM bug** (`ru_maxrss` = peak, never decreases); worker `/status` missing experiment/testgen fields the UI expects; human-annotation backend fully wired but **no UI component mounted**; feedback impact invisible to users |
| 3 | Guide page | S | No `/guide` route; StartPage has path cards but no full how-to; sidebar has a natural slot |
| 4 | Tribunal rename | XS | 8 remaining "Ragas" occurrences (sidebar ×2, login subtitle, `<title>`, package.json, types comment, localStorage key ×2) |
| 5 | Test-type compatibility | M | Metric gating happens **after** experiment creation (ExperimentRunner), driven by 3 booleans; no backend capability endpoint; turns/category/SQL columns not surfaced at selection time |
| 6 | File types + images | M | Only .txt/.pdf/.docx (50 MB); pypdf + python-docx; **zero image handling**, no vision/OCR deps; schema can absorb image-derived text without migration |
| 7 | Skills v2 | L | Parser is single-string only; no multi-file/zip; directives extracted once at upload; no user-input loop. Depends on #1's agent loop |

Recommended order: **4 → 2 → 5 → 3 → 6 → 1 → 7** (quick wins first; #7 builds on #1).

---

## Area 1 — Agentic tool calling

**Goal:** the AI under evaluation can call tools and take actions during a test, and
Tribunal scores the tool usage (right tool, right args, goal achieved).

### Current state (audit)

- `pipeline/llm.py:112-150` — `chat_completion()` central dispatch (OpenAI / Anthropic /
  Gemini / gateway). No `tools`, `tool_choice`, no tool_call parsing.
- `pipeline/bot_connectors/base.py:33-50` — `BotConnector.query()` single-shot protocol.
- `app/services/experiment_runner.py:492-549` — answer generation (bot vs RAG paths);
  multi-turn history already accumulates (lines 494-501).
- `evaluation/metrics/tool_call_accuracy.py`, `tool_call_f1.py`,
  `agent_goal_accuracy.py` — ragas wrappers exist but UI lists them under
  "Coming Soon" (`runner/MetricSelection.tsx:64-72`).
- `experiment_results.metadata_json` can store a tool trace with no schema change.

### Design

**1.1 Extend `chat_completion()` with tool support** ☐
- New optional params: `tools: list[dict] | None` (OpenAI-style JSON schema),
  `tool_choice`. Translate per provider (Anthropic `input_schema`, Gemini
  `function_declarations`).
- Return shape gains `"tool_calls": [{id, name, arguments}]` when the model stops on
  a tool call; keep `content`/`usage` unchanged so existing callers are unaffected.

**1.2 New module `pipeline/agent_loop.py`** ☐
- `async def run_agent(model, messages, tools, executor, max_steps=8) -> AgentResult`.
- Loop: chat_completion → if tool_calls → execute via `executor` → append tool result
  messages → continue; stop on final text, `max_steps`, or token budget.
- `AgentResult`: `answer`, `steps[] {tool, args, result, latency_ms}`, `usage`,
  `stop_reason`.

**1.3 Tool registry + execution modes** ☐
Tools are defined per experiment (UI + API), each with one of three execution modes:
- **`mock`** — fixture response from a static JSON map (args-pattern → response).
  Default and safest; evaluation usually only needs to check *that* the right call
  was made.
- **`simulated`** — an LLM plays the tool ("respond as a weather API would").
- **`builtin`** — real implementations shipped with Tribunal, allowlisted:
  - `search_documents` (wraps existing retrieval — reuses `pipeline/rag.py` index),
  - `read_file` (project documents / skill reference files — needed by Area 7),
  - `calculator` (safe AST eval).
  No arbitrary HTTP/code execution in v1 (security).

Storage: new `tool_definitions` table (project_id, name, description, json_schema,
mode, fixtures_json) or `experiments.tools_json` — prefer the table for reuse across
experiments.

**1.4 Experiment integration** ☐
- `experiment_runner.py`: when the experiment has tools configured, wrap the answer
  path in `run_agent()` instead of a single `chat_completion()`/connector call.
- Persist trace into `experiment_results.metadata_json["agent_trace"]`.
- Dataset support: test-set upload gains optional `reference_tool_calls` column
  (JSON list) mapping, like `reference_sql` does today
  (`TestSetUpload.tsx` column-mapping pattern, `testsets.py:520-773`).

**1.5 Enable the tool metrics** ☐
- Move `tool_call_accuracy`, `tool_call_f1`, `agent_goal_accuracy`, `topic_adherence`
  out of "Coming Soon"; gate them on `has_reference_tool_calls` / agent experiments
  (Area 5's capability system).
- Add deterministic extras: `agent_steps_count`, `tool_error_rate` (computed from the
  trace, no LLM cost).

**1.6 Frontend** ☐
- Experiment create: "Tools" section — pick tools from the registry, per-tool mode.
- Result drill-down: collapsible agent-trace timeline (step n: tool, args, result).

### Acceptance
Run an experiment where gpt-4o-mini must call `search_documents` + `calculator`,
see the per-step trace in the result view, and get `tool_call_accuracy` scored against
a `reference_tool_calls` column — with mock tools and zero real side effects.

---

## Area 2 — Worker nodes: RAM, visibility, feedback

### Bugs confirmed by audit

**2.1 RAM reporting is wrong** ☐ — `worker/routes.py:73-79` and `292-296` use
`resource.getrusage(...).ru_maxrss`, the **peak** RSS high-water mark: monotonically
increasing, never reflects freed memory, resets only on restart.
- Fix: use `psutil.Process().memory_info().rss` (add `psutil` to requirements — it is
  not currently a dependency). Report both `rss_mb` (current) and `peak_rss_mb`
  (keep `ru_maxrss`, it's still useful). Optionally add container awareness
  (`/sys/fs/cgroup/memory.max`) to show "X / Y MB" with a % bar.
- Frontend `WorkersPage.tsx:198` shows the value already — add the peak + a usage bar.

**2.2 Worker `/status` missing fields the UI expects** ☐ — `WorkersPage.tsx:238-269`
renders `active_experiments`, `active_testgens`, `max_concurrent_experiments`,
`max_concurrent_testgens`, but `worker/routes.py:287-323` never returns them →
dashboard silently shows nothing for those task types.
- Fix: either populate the fields from the worker's actual task tracking, or (if
  experiments never run on workers) remove the dead UI columns. Decide based on the
  deployment model: KG builds + persona gen run on workers today; experiments run
  in the main app. **Likely correct fix:** main app contributes its own
  "local worker" entry to `/api/workers/status` (`app/routes/health.py:51-75`) carrying
  experiment/testgen tasks from `ProgressStore`, so one dashboard shows all work.

**2.3 Show what the worker is actually doing** ☐ — tasks today expose type, stage,
step x/y, elapsed. Add: project/job name, current item detail ("question 5/50",
current document name during KG build), and est. remaining (elapsed ÷ progress).
Extend the task dicts in `worker/routes.py` + `WorkerTask` type
(`frontend/src/api/types.ts:1080-1098`) + `taskLabel()`/`taskStatus()` in
`WorkersPage.tsx:38-72`.

### Feedback system fixes

Three feedback layers exist; two are broken in practice:

**2.4 Human annotation has no UI** ☐ — backend complete
(`app/routes/annotations.py:57-174`, `human_annotations` table, 20% deterministic
sampling) but `HumanAnnotationPanel.tsx` is **not mounted** in the experiment results
view. Fix: mount it in the Analyze/experiment-results page behind an "Annotate
sample" tab; wire `annotation-sample` GET + annotations POST; show progress
("12/20 annotated").

**2.5 Verify `annotateJudgeClaim()` wiring** ☐ — `MultiLLMJudgePanel.tsx` imports it
from `lib/api`; confirm the export exists in the `frontend/src/api/` domain modules
(post api.ts split) and the request actually fires. Add a Vitest covering the
submit path.

**2.6 Close the feedback loop visibly** ☐ — claim annotations feed
`get_judge_reliability` (`app/routes/multi_llm_judge.py:279-389`) which can exclude
unreliable evaluators, but users never see the effect. Fix:
- Reliability panel in results: per-evaluator accuracy %, excluded badges.
- After annotating: toast/banner "Feedback saved — evaluator reliability updated".
- Show adjusted vs raw judge score when exclusions apply.

### Acceptance
Workers page shows live (not peak) RAM with a capacity bar; every running task shows
job name + item-level progress; a user can annotate a result sample from the UI and
immediately see judge-reliability numbers move.

---

## Area 3 — Guide page

### Current state
No dedicated help. StartPage (`StartPage.tsx:35-174`) has two path cards;
metric descriptions exist (`runner/MetricSelection.tsx:74-132`); empty states exist.
Router: `App.tsx:18-43`; sidebar: `Stepper.tsx` + `WorkspaceLayout.tsx:95-165`.

### Plan

**3.1 `/guide` route + sidebar link** ☐ — new `GuidePage.tsx`, link in the utility
nav (next to Workers). Content as data (`guideContent.ts`) so it's easy to maintain.

**3.2 Content sections** ☐
1. **What is Tribunal** — 3-sentence overview + the two paths diagram.
2. **Path A: test an external agent** — step-by-step with screenshots: connect bot →
   upload/generate questions → pick metrics → run → read results.
3. **Path B: build & evaluate a RAG pipeline** — setup → chunk → embed → KG →
   generate test set → experiment → analyze.
4. **Dataset format reference** — table of every column the uploader understands
   (question, reference_answer, contexts, category, turns, reference_sql,
   schema_contexts, reference_data, + future reference_tool_calls) with example CSV
   rows and which metrics each column unlocks (powered by the same capability map as
   Area 5 — single source of truth).
5. **Metric glossary** — reuse `METRIC_DESCRIPTIONS`, grouped, with cost tags
   (LLM vs free) and "requires" notes.
6. **Skill Arena how-to** — what a SKILL.md is, what adherence/lift mean.
7. **FAQ / troubleshooting** — judge model keys, worker offline, stuck experiments.

**3.3 Contextual help** ☐ — small `<HelpTip>` ui primitive (info icon + popover)
seeded on the 5 most confusing controls (judge model slots, concurrency, presets,
bot returns-contexts toggle, chunking method). Each links to the relevant guide
section via anchor (`/guide#datasets`).

### Acceptance
A first-time user can go from login to a completed experiment using only the guide
page; every uploader and metric picker links to the format reference.

---

## Area 4 — Finish the Tribunal rename

All remaining occurrences (audit-verified):

| File | Line | Current | Change |
|------|------|---------|--------|
| `frontend/src/components/WorkspaceLayout.tsx` | 102 | sidebar header "Ragas" | "Tribunal" |
| `frontend/src/components/WorkspaceLayout.tsx` | 141 | mobile drawer "Ragas" | "Tribunal" |
| `frontend/src/pages/LoginPage.tsx` | 90 | subtitle "Ragas Platform" | "Evaluation Platform" (keep "Tribunal" logo above) |
| `frontend/index.html` | 6 | `<title>Ragas Platform</title>` | `<title>Tribunal</title>` |
| `frontend/package.json` | 2 | `"name": "ragas-platform"` | `"tribunal"` |
| `frontend/src/api/types.ts` | 1 | comment "Ragas Platform backend" | "Tribunal backend" |
| `frontend/src/contexts/ProjectContext.tsx` | 12 | `STORAGE_KEY = 'ragas_selected_project'` | `'tribunal_selected_project'` **with migration**: on read, fall back to old key and copy forward |
| `frontend/src/pages/pages.smoke.test.tsx` | 44 | same key in test | update with the migration |

Also sweep: README badges/title, docker-compose service names *labels only* (don't
break deploys), FastAPI `title=` in `main.py` and `worker/main.py`, OpenAPI docs
title. Note: "ragas" the *library* and metric names stay — only product branding
changes.

### Acceptance
`grep -ri "ragas" frontend/src frontend/index.html` returns only the ragas-library
metric references; old localStorage users keep their selected project.

---

## Area 5 — Capability-aware test/metric selection

**Goal:** when a user picks a test set (or connector/mode), incompatible
test types are disabled *at selection time* with a reason — not discovered later.

### Current state
- Gating exists only inside `ExperimentRunner.tsx:16-30` via 3 booleans
  (`has_reference_contexts`, `has_reference_sql`, `has_reference_data`) +
  `CONTEXT_REQUIRED_METRICS` (`MetricSelection.tsx:44-57`). Good UX (strikethrough +
  reason tooltip) but late, incomplete, and frontend-only.
- Not covered: `turns` (conversation metrics), `category` (refusal_accuracy),
  reference-answer presence (context_recall, factual_correctness need ground truth),
  future `reference_tool_calls`.
- Backend never validates metric/dataset compatibility.

### Plan

**5.1 Single source of truth: backend capability model** ☐
- New module `evaluation/capabilities.py`:
  - `METRIC_REQUIREMENTS: dict[str, set[Requirement]]` — e.g.
    `context_recall: {CONTEXTS, REFERENCE_ANSWER}`, `refusal_accuracy: {CATEGORY}`,
    `conversation_retention: {TURNS}`, `sql_semantic_equivalence: {REF_SQL}`,
    `tool_call_accuracy: {REF_TOOL_CALLS}`, `multi_llm_judge: {}` …
  - `dataset_capabilities(test_set_id) -> set[Requirement]` computed from actual
    rows (does any approved question have non-empty contexts? turns? category? …).
- New endpoint `GET /projects/{id}/test-sets/{tsid}/capabilities` returning
  `{capabilities: [...], metrics: {metric: {available: bool, missing: [...]}}}`.
  Connector-derived capabilities (bot_returns_contexts, mode=rag) merged in by a
  query param or computed client-side.

**5.2 Frontend: gate at every selection point** ☐
- `ExperimentCreate.tsx`: after test-set pick, fetch capabilities; show a capability
  chip row ("✓ contexts · ✓ ground truth · ✗ turns · ✗ SQL") so users see what the
  set supports *before* creating the experiment.
- `MetricSelection.tsx`: replace the 3 hand-rolled booleans with the endpoint's
  per-metric availability map; keep the strikethrough + reason tooltip UX. Hide
  (not just disable) whole groups when zero metrics in the group are available.
- Skill Arena `TrialCreate`: same pattern (needs ≥1 approved question — already
  checked — surface it as a capability chip too).

**5.3 Backend validation** ☐ — experiment run endpoint rejects metrics whose
requirements the dataset doesn't meet (422 with the missing-capability list), so the
API is safe regardless of UI.

**5.4 Uploader feedback** ☐ — after CSV upload/column mapping, show "this test set
unlocks: …" using the same map (also feeds Guide §4).

### Acceptance
Selecting a context-less Q&A CSV immediately shows context metrics struck out with
"requires retrieved contexts"; a turns-less set hides conversation metrics; the API
refuses a hand-crafted request for an unavailable metric.

---

## Area 6 — More file types + image reading

### Current state
- Documents: `.txt/.pdf/.docx` only (`config.py:79`), 50 MB, extension-based check
  (`app/routes/documents.py:15-67`); pypdf + python-docx.
- Zero image handling; no vision/OCR deps. `documents.content` (TEXT) +
  `metadata_json` can hold image-derived text **without schema migration**.

### Plan

**6.1 Easy text formats** ☐ — extend `ALLOWED_FILE_TYPES` + parser dispatch in
`documents.py`:
- `.md` — store raw (it's already text; chunking has a `markdown` splitter).
- `.html/.htm` — `beautifulsoup4` → text (strip nav/script).
- `.pptx` — `python-pptx` → slide-by-slide text with `[Slide n]` markers.
- `.xlsx` — `openpyxl` → sheet → markdown tables (cap rows).
- `.csv/.tsv` (as *document*, distinct from test-set upload) → markdown table.
- `.json/.yaml` — pretty-printed text.
Parser layer: extract a `parse_document(filename, data) -> str` registry from the
inline if/elif in `documents.py` (one function per type, unit-testable).

**6.2 Images via vision LLM (recommended over OCR)** ☐
- Accept `.png/.jpg/.jpeg/.webp` (size cap ~10 MB each).
- Extend `chat_completion()` (or a sibling `vision_completion()`) in
  `pipeline/llm.py` to send image content blocks — all three configured providers
  (OpenAI, Anthropic, Gemini) support vision natively, so **no new deps**; reuse
  the user's existing keys. This also future-proofs Area 1 (agents that see images).
- On upload: vision model produces a structured extraction (full OCR-style text +
  a one-paragraph description); store as `documents.content`, original file kept on
  disk under `data/uploads/{project_id}/`, path + `source_kind: "image"` in
  `metadata_json`.
- Config: `VISION_MODEL` env (default a cheap one, e.g. gpt-4o-mini / gemini-flash);
  graceful 422 if no provider key supports vision.
- Optional fallback (off by default): `pytesseract` local OCR for air-gapped
  deployments — keep out of base requirements.

**6.3 PDF with embedded images** ☐ (phase 2) — if a PDF page yields <50 chars of
text via pypdf, render that page (`pypdf` images or `pdf2image`) and run the same
vision extraction; merge into page text.

**6.4 Frontend** ☐ — `DocumentUpload.tsx`: update `accept` + the helper text
(line 145); show a "vision-extracted" badge on image docs; preview extracted text.

### Acceptance
Upload a .pptx, an .html page, and a .png screenshot; all three appear as documents,
chunk normally, and are retrievable in RAG experiments; the .png's text content is
searchable.

---

## Area 7 — Skills v2: multi-file, progressive disclosure, user input

### Current state
- Single string only: `SkillCreate.content` 20–200k chars (`app/models.py:868-879`);
  `skills` table stores one TEXT blob (`db/init.py:437-446`); directives extracted
  once at upload by an LLM call (`evaluation/skills/parser.py:93-133`).
- Trials inject the full skill as system context, single-shot, judge adherence after
  (`app/services/skill_trials.py:43-159`).
- No references/, no zip, no user-interaction handling.

### Design principle
Real Claude-style skills are **directories** (SKILL.md + references/*.md +
scripts/*) that rely on *progressive disclosure* (the agent reads extra files only
when needed) and sometimes *ask the user questions*. Tribunal should evaluate them
the way they actually run: give the model a file-reading tool and a simulated user.
**This is why Area 7 depends on Area 1's agent loop.**

### Plan

**7.1 Multi-file skill ingestion** ☐
- New table `skill_files (id, skill_id FK, path TEXT, content TEXT)`; `skills.content`
  remains the entry-point SKILL.md.
- Upload paths: (a) existing single .md (unchanged); (b) **.zip** — backend extracts,
  finds SKILL.md (root or single top dir), stores the rest as skill_files. Limits:
  ≤100 files, ≤5 MB total text, text-decodable files only (skip binaries with a
  warning list in the response).
- Parser: still parses *only* SKILL.md for directives, but records
  `referenced_paths` (scan for relative links / `references/` mentions) in the
  parsed JSON so the UI can show "links to 4 reference files, 3 found / 1 missing".
- Frontend `SkillUpload.tsx`: accept `.zip`; file-tree preview of stored files.

**7.2 Progressive disclosure during trials** ☐
Two evaluation modes per trial (user-selectable):
- **`inline` (today's behavior, default for single-file)** — full SKILL.md as system
  context.
- **`agentic`** — system context = SKILL.md only; model gets a builtin `read_file`
  tool (Area 1.3) scoped to that skill's `skill_files`. The agent loop lets it pull
  references on demand, exactly like a real harness.
- New adherence inputs: the judge also receives which files were read; new
  deterministic metrics: `files_read_count`, `disclosure_efficiency`
  (did it read files it needed? did it read everything wastefully?).
- Matrix UI: show 📄 n-files-read per cell; trace timeline reuses Area 1.6's
  component.

**7.3 User-input handling** ☐
Skills that ask the user questions ("which option do you want?") break batch
evaluation. Strategy — **simulated user** with scripted overrides:
- Detection: parser flags `interaction_required` when SKILL.md contains
  ask-the-user directives (LLM extraction prompt gains this field).
- Trial config gains a **user simulator**: when the model's response ends in a
  question / explicit ask (detected by a cheap LLM check or the model calling a
  provided `ask_user` tool), the loop answers with:
  1. **Scripted answers** — optional per-question `user_inputs` JSON on the test
     question (uploader column `user_inputs`), tried first by matching order;
  2. **Persona simulator** — fallback LLM acting as the user, prompted with the
     test question's intent + persona ("answer briefly and consistently with the
     original request") — bounded to ≤3 exchanges per cell.
- The full exchange is stored in `trace_json` and shown in drill-down; adherence
  judging sees the *whole transcript*, not just the last message.
- Interactive mode (a human answers live) explicitly **out of scope** — batch trials
  are the product; note it as a possible future "debug single cell" feature.

**7.4 Long-skill handling** ☐ — parser currently truncates at 24k chars
(`parser.py:105`). For multi-file/long skills: parse directives from SKILL.md
(usually short — the references hold the bulk); raise the judge's context discipline
by passing only directives + transcript (already the case). Document the 200k/24k
limits in the Guide.

### Acceptance
Upload a zipped skill (SKILL.md + 3 reference files) that asks the user one
clarifying question; run an agentic trial across 2 models + baseline; the matrix
shows adherence, files-read, and the simulated-user exchange in the per-cell trace.

---

## Suggested phasing

| Phase | Contents | Size |
|-------|----------|------|
| **P1 — Quick wins** | Area 4 (rename, with localStorage migration) + 2.1 RAM fix + 2.5 claim-annotation wiring check | ~1 day |
| **P2 — Feedback & workers** | 2.2 status fields / local-worker entry, 2.3 task detail, 2.4 annotation UI, 2.6 visible feedback loop | 2–3 days |
| **P3 — Capability gating** | 5.1 backend model + endpoint, 5.2 UI gating, 5.3 API validation, 5.4 uploader feedback | 2–3 days |
| **P4 — Guide** | 3.1–3.3 (reuses capability map from P3) | 1–2 days |
| **P5 — Files & images** | 6.1 text formats, 6.2 vision extraction, 6.4 UI (6.3 PDF-images optional) | 2–3 days |
| **P6 — Agent core** | 1.1 tools in chat_completion, 1.2 agent loop, 1.3 registry (mock+builtin), 1.4 runner integration, 1.5 metrics, 1.6 UI | 4–6 days |
| **P7 — Skills v2** | 7.1 zip ingestion, 7.2 agentic mode, 7.3 user simulator, 7.4 limits | 3–5 days |

Each phase independently shippable. Definition of done per phase: `ruff check .`
green, unit+integration tests green (mocked LLMs), `tsc`/eslint/`vite build` green,
one manual end-to-end pass of the affected workflow.

### Env note
Use `C:\venvs\ragas-eval\Scripts\python.exe` (repo `.venv` corrupted by OneDrive).
Tests need `OPENAI_API_KEY=sk-dummy`.

### Risks
| Risk | Mitigation |
|------|-----------|
| Agent loops runaway cost | `max_steps` + token budget per cell/question; mock tools default |
| Vision extraction cost on big uploads | per-image size cap, batch confirm dialog with image count, cheap default model |
| Zip upload security | text-only extraction, path traversal guard (reject `..`/absolute paths), file count + size caps |
| Simulated user drifts from intent | scripted answers take priority; simulator prompt pinned to original question; ≤3 exchanges |
| Worker `/status` change breaks dashboard | additive fields only; frontend renders missing fields as before |
