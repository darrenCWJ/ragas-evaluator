# Frontend Codemap

**Last Updated:** 2026-06-13  
**Entry Point:** `frontend/src/main.tsx`  
**Tech Stack:** React 18 + TypeScript + Vite + Tailwind CSS (dark-theme design system)

---

## Architecture

```
main.tsx
  BrowserRouter (basename="/app")
    App.tsx
      ErrorBoundary
        AuthProvider
          ProjectProvider
            Routes
              /login             -> LoginPage  (outside WorkspaceLayout)
              WorkspaceLayout    (auth guard + project guard)
                /start           -> StartPage
                /setup           -> SetupPage
                /build           -> BuildPage
                /test            -> TestPage
                /experiment      -> ExperimentPage
                /analyze         -> AnalyzePage
                /knowledge-graph -> KnowledgeGraphPage
                /personas        -> PersonasPage
                /skills          -> SkillsPage
                /workers         -> WorkersPage
              /* redirect to /start
```

---

## Entry / Bootstrap

| File | Role |
|------|------|
| `frontend/vite.config.ts` | `base: "/app/"`, proxy `/api` -> `http://localhost:8000`, outDir `dist` |
| `frontend/src/main.tsx` | Creates root, wraps in `BrowserRouter basename="/app"`, mounts App |
| `frontend/src/App.tsx` | `ErrorBoundary > AuthProvider > ProjectProvider > Routes`; login route is outside the layout wrapper |
| `frontend/src/index.css` | Tailwind directives, reduced-motion media query, scrollbar theming |

---

## Contexts

| File | Role |
|------|------|
| `contexts/AuthContext.tsx` | status->me two-step init: calls `fetchAuthStatus` first, then `fetchCurrentUser` when auth is enabled. Exposes `user`, `loading`, `authEnabled`, `registrationOpen`, `refresh`, `logout`. Listens for `tribunal:unauthorized` window event to clear user and trigger route-guard redirect. Open mode (`authEnabled=false`) never redirects anywhere. |
| `contexts/ProjectContext.tsx` | Holds the active `Project` object; persists to/from `localStorage` under key `ragas_selected_project`. Exposes `project`, `setProject`, `clearProject`. |

---

## Layouts

### WorkspaceLayout (`layouts/WorkspaceLayout.tsx`)

```
WorkspaceLayout
  Auth guard: if authLoading          -> full-screen Spinner
              if authEnabled && !user  -> Navigate /login
              open mode               -> never redirects
  Project guard: if !project && not on /setup -> Navigate /setup
  Desktop sidebar (w-60, hidden on mobile)
    Logo "R" badge
    Stepper (scrollable nav)
    SidebarFooter
  Mobile drawer (fixed, slide-in, toggled by hamburger)
    same Stepper + SidebarFooter
  Header bar
    Hamburger (mobile only)
    "Pipeline Workspace" title
    ProjectSelector (dropdown)
  <main> bg-deep
    <Outlet /> (page content)
```

`SidebarFooter` shows `user.name` + Admin badge + email when `authEnabled && user`; Sign Out calls `logout()` then navigates to `/login`. Always shows `v{version}`.

### Stepper (`components/Stepper.tsx`)

Six pipeline stages plus four utility links below a separator:

| Step | Path | Locked when |
|------|------|-------------|
| -> Start | `start` | never |
| 01 Setup | `setup` | never |
| 02 Build | `build` | no project |
| 03 Test | `test` | no project |
| 04 Experiment | `experiment` | no project |
| 05 Analyze | `analyze` | no project |
| (separator) | | |
| Knowledge Graphs | `knowledge-graph` | never |
| Personas | `personas` | never |
| Skill Arena | `skills` | never |
| Workers | `workers` | never |

Stage completion ticks: `useStageCompletion` polls six API endpoints in parallel on every pathname change (`docs, chunkConfigs, embeddingConfigs, ragConfigs, testSets, experiments`). Completed stages show a checkmark badge (emerald). Active stage shows accent-glow background + left accent bar.

---

## API Layer

### `api/client.ts` -- shared core

| Symbol | Purpose |
|--------|---------|
| `ApiError` | `Error` subclass with `.status: number` |
| `UNAUTHORIZED_EVENT` | `"tribunal:unauthorized"` -- window event constant |
| `request<T>` | JSON fetch wrapper; fires `UNAUTHORIZED_EVENT` on non-auth 401; returns `undefined` on 204 |
| `formRequest<T>` | FormData POST; same error handling |

Auth-endpoint exemption: `notifyUnauthorized` skips dispatch for paths starting `/api/auth/` so login probes do not trigger global sign-out.

### `api/index.ts` -- barrel re-exporting all domain modules and types

### `api/types.ts` -- all shared TypeScript interfaces (no runtime code)

### Domain modules (15)

| Module | Purpose |
|--------|---------|
| `auth.ts` | `fetchAuthStatus`, `registerUser`, `loginUser`, `logoutUser`, `fetchCurrentUser`, user-admin CRUD, project membership |
| `projects.ts` | Project CRUD, judge-model config, config defaults |
| `documents.ts` | Document upload (`formRequest`), list, delete |
| `chunks.ts` | Chunk config CRUD, chunk preview, chunk generate |
| `embeddings.ts` | Embedding config CRUD, embed action |
| `rag.ts` | RAG config CRUD, RAG test query |
| `testsets.ts` | Test set CRUD, question annotation, bulk annotation, upload preview/confirm, generation progress polling, cancellation |
| `personas.ts` | Saved persona CRUD, AI persona generation, bulk save |
| `kg.ts` | KG build/reset/rebuild-links, progress polling, stream graph data (SSE ReadableStream), fetch all KGs, delete |
| `experiments.ts` | Experiment CRUD, `runExperimentSSE` (POST /run + `observeExperimentProgress`), cancel, progress snapshot, results, export, suggestions, batch apply, prompt doctor, delta, compare, history, source verification |
| `insights.ts` | Quality audit, corpus coverage, experiment category breakdown |
| `annotations.ts` | Human annotation sample, create annotation, evaluator accuracy |
| `metrics.ts` | Custom metric CRUD |
| `workers.ts` | Worker status, clear persona/build tasks |
| `skills.ts` | Skill CRUD, trial CRUD, trial matrix, trial results, apply preferred model |

`lib/api.ts` is a one-line compatibility barrel: `export * from '../api'`

---

## Hooks

| File | Behaviour |
|------|-----------|
| `hooks/useFetch.ts` | `useFetch<T>(fn, deps)` -- loads data with `{data, loading, error, reload}`. Generation counter prevents stale-resolution races on dep change or unmount. |
| `hooks/usePolling.ts` | `usePolling(fn, intervalMs, active, onPersistentFailure?)` -- loop calls `fn()` returning `continue|stop`; tolerates transient errors; cuts off after 5 consecutive failures, sets `error`, calls `onPersistentFailure`. |
| `hooks/useConfirm.ts` | `useConfirm<Id>()` -- arm/confirm inline-delete pattern; returns `{confirmingId, requestConfirm, clear, isConfirming}`. |
| `hooks/useExperimentStream.ts` | `useExperimentStream({projectId, experiment, onComplete})` -- unified SSE lifecycle. Auto-reconnects on mount when experiment is running (pre-populates from progress snapshot). `startRun(opts)` POSTs `/run` then calls `observeExperimentProgress`. `RunState` discriminated union: idle | running | completed | error | connection_lost. Exposes `startRun`, `abort`, `refreshStatus`, `completedLog`, `elapsed`, `errorCount`, `experimentMeta`. |

---

## Pages

| Page | Route | Purpose |
|------|-------|---------|
| `LoginPage` | `/login` | Login + register tabs; open-mode shows first-admin bootstrap notice; redirects to `/start` when already authenticated |
| `StartPage` | `/start` | Two-path progress card (external-agent vs RAG-pipeline); "What's next" highlight; step rows with completion ticks via four `useFetch` calls |
| `SetupPage` | `/setup` | Project selection/creation; `BotConnectorConfig`; `ExternalBaselineUpload`; `CustomMetricBuilder`; `CsvUploadsList`; `ProjectMembersPanel` (auth mode only) |
| `BuildPage` | `/build` | Document upload + list; `ChunkConfigPanel` with chunk preview; `EmbeddingConfigPanel`; `RagConfigPanel`; `PipelineStatus` |
| `TestPage` | `/test` | Test set list; inline question browser; `TestSetGenerate` wizard; `TestSetUpload` CSV import; `TestSetInsights` quality audit |
| `ExperimentPage` | `/experiment` | Experiment list; `ExperimentCreate` form; single-experiment `ExperimentRunner` + `useExperimentStream`; multi-select compare (2-5) via `ExperimentCompare`; `ExperimentHistory` trend |
| `AnalyzePage` | `/analyze` | Completed-experiment selector; `ExperimentResults`; `ExperimentSuggestions` + apply; `ExperimentDelta`; `SourceVerificationPanel`; `HumanAnnotationPanel`; `ProjectReportPanel` |
| `KnowledgeGraphPage` | `/knowledge-graph` | Cross-project KG list via `KGCard`; graph streaming into `KGGraphView` + `KGNodeDetail` |
| `PersonasPage` | `/personas` | Inline CRUD for saved personas (edit/delete with confirm) |
| `SkillsPage` | `/skills` | `SkillLibrary` + `SkillUpload`; `TrialCreate`; `TrialList` -> `TrialMatrix` -> `TrialDrilldown` + `TraceTimeline`; apply preferred model |
| `WorkersPage` | `/workers` | Worker health dashboard; task list per worker; `UserAccountsCard` (admin only) |

---

## Components

### `components/ui/` -- primitives

| Component | Purpose |
|-----------|---------|
| `Button` | Variant-aware button with `loading` spinner state |
| `Card` | Surface container with `padding` prop |
| `Label` | Form label |
| `TextInput` | Styled `<input>` |
| `TextArea` | Styled `<textarea>` |
| `Select` | Styled `<select>` |
| `FormField` | Label + children + optional hint wrapper |
| `Spinner` | Animated loading indicator, `size` prop |
| `ScoreBar` | Filled bar for 0-1 scores using score-high/mid/low thresholds |
| `ErrorAlert` | Dismissible error message box |
| `EmptyState` | Centered empty-content placeholder |
| `ConfirmButtons` | Inline confirm/cancel pair for destructive actions |
| `CopyButton` | Clipboard copy with visual feedback |

All exported via `components/ui/index.ts` barrel.

### `components/test/generate/` -- test-set generation wizard sub-components

| Component | Purpose |
|-----------|---------|
| `SourceFields` | Chunk config selector, name, size, sample-size inputs |
| `KGBuildPanel` | KG build/reset controls + `KgSourceInfoCard` status badge |
| `PersonaSection` | AI-generated or manual persona editor; save to library |
| `DistributionSliders` | Even-redistribution sliders for query-type or category percentages |
| `GraphRagSection` | GraphRAG toggle, KG source (chunks vs documents), category sliders |
| `GenerateProgress` | Live stage labels + progress bar + cancel; polls `fetchGenerationProgress` |
| `constants.ts` | `QUERY_TYPES`, `QUESTION_CATEGORIES`, `GRAPH_RAG_CATEGORIES`, default distributions |

### `components/test/` -- test set management

| Component | Purpose |
|-----------|---------|
| `TestSetGenerate` | Full generation wizard orchestrating all `generate/` sub-components |
| `TestSetUpload` | CSV upload -> `previewTestSetUpload` -> column mapping (question, answer, contexts, category, turns, ref_sql, schema_ctx, ref_data) -> `confirmTestSetUpload` |
| `TestSetInsights` | Quality audit (quick/deep LLM) + corpus coverage panel |
| `TestSetList` | List with status badges, select/delete |
| `QuestionList` | Paginated question browser with approve/reject/edit inline |
| `QuestionCard` | Individual question display with annotation controls |
| `BulkActions` | Approve-all / reject-all / export CSV |

### `components/experiment/runner/` -- experiment run controls

| Component | Purpose |
|-----------|---------|
| `MetricSelection` | Checkbox grid with metric groups (LLM/NVIDIA/embedding/string/domain); `PRESET_RECOMMENDED` one-click; warns when context metrics selected but bot has no contexts |
| `RubricsForm` | 5-level rubric criteria editor (score1-score5 descriptions); shown when `rubrics_score` selected |
| `JudgeSettings` | Per-slot judge model + temperature; saves as project default via `updateProjectJudgeDefaults` |
| `RunLog` | In-flight per-question pipeline display (`InFlightDetail`) + auto-scrolling completed Q&A feed |

### `components/experiment/` -- experiment results and analysis

| Component | Purpose |
|-----------|---------|
| `ExperimentRunner` | Wires `useExperimentStream`; renders `MetricSelection`, `RubricsForm`, `JudgeSettings`, run button, `RunLog` |
| `ExperimentSuggestions` | Loads/generates suggestions; `PromptDoctorPanel` embedded; batch apply with outcome badges |
| `PromptDoctorPanel` | Runs prompt-doctor LLM analysis; renders revised prompt + additions (persona/guardrail/phase) with `CopyButton` |
| `CategoryBreakdown` | Per-category metric breakdown table with weakest-question list |
| `ExperimentResults` | Per-question score table; metric aggregates with 95% CI; CSV export; embeds `MultiLLMJudgeDashboard` and `CategoryBreakdown` |
| `ExperimentDelta` | Baseline vs iteration: `ConfigChange` list + per-metric `MetricDelta` with direction badges |
| `ExperimentCompare` | Multi-experiment (2-5) side-by-side comparison via `CompareResult` |
| `ExperimentHistory` | Score trend across all completed experiments |
| `ExperimentCreate` | New experiment form: name, test set, RAG config or bot config selector |
| `ExperimentList` | Sortable list with status badges, compare checkboxes, delete/reset |
| `HumanAnnotationPanel` | Sample-based human rating (accurate/partial/inaccurate) + evaluator agreement stats |
| `MultiLLMJudgeDashboard` | Judge reliability stats + claim annotation UI |
| `MultiLLMJudgePanel` | Per-result judge verdict viewer |
| `QuestionResultRow` | Expandable row: question, response, contexts, per-metric scores with color coding |
| `SourceVerificationPanel` | Citation status (verified/hallucinated/inaccessible/unverifiable) per result |
| `ProjectReportPanel` | Project-wide report: all experiments + bot summary |
| `scoreUtils.ts` | `humanizeMetric`, `scoreBarColor`, `scoreBgColor`, `scoreTextColor`; thresholds: >= 0.8 high (emerald), >= 0.5 mid (amber), < 0.5 low (red) |

Outcome badges on applied suggestions: `SuggestionOutcomeOverall` = improved | regressed | mixed | inconclusive; rendered inline in suggestion card after batch apply.

### `components/skills/` -- Skill Arena

| Component | Purpose |
|-----------|---------|
| `SkillUpload` | Upload/parse skill doc; classifies directives with `DirectiveKindBadge` (behavior/format/prohibition/tone) |
| `SkillLibrary` | Lists skills with directive count; select to run trial |
| `TrialCreate` | Form: skill, test set, model slots (LLM or bot config), include-baseline toggle |
| `TrialList` | Trial history; polls running trials via `usePolling`; click row -> `TrialMatrix` |
| `TrialMatrix` | Adherence/format/latency/token grid by model x variant (skill vs baseline); lift delta per model; apply-as-preferred-model action |
| `TrialDrilldown` | Per-question per-directive verdict list for a selected matrix cell |
| `TraceTimeline` | Gantt-style span bars (prepare/query/judge) from `TraceSpan[]` |

### `components/setup/` -- setup panel components

| Component | Purpose |
|-----------|---------|
| `BotConnectorConfig` | Bot connector CRUD (glean/openai/claude/deepseek/gemini/custom/csv) |
| `ApiEndpointConfig` | Raw API endpoint + key + headers config |
| `ExternalBaselineUpload` | Upload external Q&A CSV with column mapping |
| `BaselinePreview` | Preview uploaded baseline rows |
| `CsvUploadsList` | List of uploaded CSV baselines with row counts |
| `CustomMetricBuilder` | Create/edit custom metrics with few-shot examples (integer_range/similarity/rubrics/instance_rubrics/criteria_judge/reference_judge) |
| `ProjectMembersPanel` | Add/remove project members by email; shows owner + member list |

### `components/admin/`

| Component | Purpose |
|-----------|---------|
| `UserAccountsCard` | Lazy-loaded admin panel (expands on demand); role toggle per user; guards against removing last admin |

### `components/kg/`

| Component | Purpose |
|-----------|---------|
| `KGCard` | Per-KG status card with build/reset/rebuild-links controls; polls build progress inline |
| `KGGraphView` | Graph render of streamed nodes + edges |
| `KGNodeDetail` | Keyphrase and edge detail panel for a selected node |

### Other components

| Component | Purpose |
|-----------|---------|
| `ErrorBoundary` | Class component; catches render errors; shows fallback |
| `ProjectSelector` | Dropdown to create/select project; stores selection in `ProjectContext` |

---

## Key Flows

### Login / Auth Guard

```
1. main.tsx mounts BrowserRouter -> App.tsx
2. AuthProvider.refresh():
   GET /api/auth/status
     auth_enabled=false -> open mode; setUser(null); loading=false; never redirects
     auth_enabled=true  -> GET /api/auth/me
         200 -> setUser(me)
         401 -> setUser(null)
3. WorkspaceLayout:
   authLoading=true        -> Spinner
   authEnabled && !user    -> Navigate /login
4. LoginPage: POST /api/auth/login -> refresh() -> navigate("/start")
5. Any API 401 on non-/api/auth/* path:
   -> window.dispatchEvent("tribunal:unauthorized")
   -> AuthContext listener -> setUser(null)
   -> WorkspaceLayout redirects to /login
```

### Experiment Run via useExperimentStream

```
1. User configures metrics / rubrics / judge settings in ExperimentRunner
2. startRun():
   POST /api/projects/{p}/experiments/{id}/run
   {metrics, rubrics, concurrency, multi_llm_judge_evaluators,
    judge_model_assignments, judge_temperature_assignments}
   -> background task starts; response has experiment_id + metrics
3. observeExperimentProgress():
   GET /api/projects/{p}/experiments/{id}/progress  (SSE ReadableStream)
   - retries up to 10x with 500ms gaps when 409 (task not yet registered)
   - SSE event types: started / progress / completed / error
4. RunState: idle -> running -> completed | error | connection_lost
5. onCompleted -> onComplete() callback -> parent reloads experiment list

Auto-reconnect (already-running experiment on mount):
   fetchProgressSnapshot() -> pre-populate RunState with real progress
   observeExperimentProgress() -> same callbacks
```

### Suggestion Apply + Outcome Display

```
1. ExperimentSuggestions loads suggestions for selected experiment
2. User selects one or more; clicks Apply
   POST /api/projects/{p}/experiments/{id}/suggestions/apply
   -> BatchApplyResult: {suggestions, new_experiment, new_rag_config, changes}
3. new_experiment.baseline_experiment_id = original experiment id
4. User runs new_experiment on ExperimentPage
5. After run: suggestions[].outcome populated
   .status:  pending | incomparable | evaluated
   .overall: improved | regressed | mixed | inconclusive
   Per-metric SuggestionOutcomeMetric: delta + lo/hi CI + verdict badge
```

### Skill Trial Lifecycle

```
1. SkillsPage: parallel useFetch for skills, trials, test sets, judge models, bots
2. TrialCreate: POST /api/projects/{p}/skills/trials
   -> {trial_id, status:"pending", total_cells}
3. TrialList polls running trials via usePolling until status !== "running"
4. Completed trial click -> TrialMatrix: adherence grid by model x variant
5. Matrix cell click -> TrialDrilldown: per-question directive verdicts
   + TraceTimeline: prepare/query/judge span bars
6. Apply button -> PATCH /api/projects/{p}/skills/trials/{t}/apply-model
   -> Project.preferred_model updated
```

---

## Conventions

### Design Tokens (dark theme, defined in `tailwind.config`)

| Token | Usage |
|-------|-------|
| `bg-deep` | Page background (darkest layer) |
| `bg-base` | Sidebar background |
| `bg-card` | Card surfaces |
| `bg-elevated` | Hover states |
| `bg-input` | Form input backgrounds |
| `text-primary` / `text-secondary` / `text-muted` | Text hierarchy |
| `border-border` | Dividers and outlines |
| `accent` / `accent-glow` | Indigo-purple accent; active-state glow |
| `score-high` / `score-mid` / `score-low` | Emerald / amber / red for metric scores |
| `text-2xs` / `text-micro` | Sub-xs sizes used in sidebar and badges |

### Patterns

- `useFetch(fn, deps)` is the standard read-only data-loading primitive; prefer over raw `useEffect + useState`
- `useConfirm` for all inline destructive-action confirm flows
- `lib/api.ts` is a one-line re-export barrel; both `../lib/api` and `../api` resolve identically
- Domain modules use only `request` / `formRequest` from `client.ts` -- no HTTP client class or Axios
- All types live exclusively in `api/types.ts`; domain modules import from there, never define their own
- ESLint baseline is standard Vite React + TypeScript config; no custom overrides detected
