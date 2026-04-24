# Frontend Codemap

**Last Updated:** 2026-04-24  
**Entry Point:** `frontend/src/main.tsx`  
**Tech Stack:** React 18 + TypeScript + Vite + Tailwind CSS

## Architecture

```
┌──────────────────────────────────────────────────────┐
│              React SPA (Vite Dev Server)              │
│           localhost:5173 (dev) or /app/ (prod)        │
├──────────────────────────────────────────────────────┤
│                                                       │
│ frontend/src/main.tsx ──→ App.tsx                    │
│                                                       │
│ App.tsx                                               │
│ ├─ Router setup (React Router v6)                    │
│ ├─ Project context + API client                      │
│ └─ Layout: Header, Sidebar, Outlet                   │
│                                                       │
│ Pages (src/pages/)                                   │
│ ├─ ProjectsPage         — List workspaces            │
│ ├─ ProjectPage          — Project dashboard          │
│ ├─ DocumentsPage        — Upload, chunk preview      │
│ ├─ RAGConfigPage        — Pipeline configuration     │
│ ├─ TestSetPage          — Test generation, KG view   │
│ ├─ ExperimentPage       — Run evaluation             │
│ ├─ ResultsPage          — Per-question metrics       │
│ ├─ SuggestionsPage      — Recommendations            │
│ └─ ComparisonPage       — Two-experiment delta       │
│                                                       │
│ Components (src/components/)                         │
│ ├─ ProjectSelector      — Dropdown to switch project │
│ ├─ DocumentUploader     — File upload + drag-drop    │
│ ├─ ChunkPreview         — Show chunks before commit  │
│ ├─ ConfigEditor         — RAG config builder         │
│ ├─ ExperimentRunner     — Start run + progress       │
│ ├─ ResultsTable         — Per-question scores        │
│ ├─ MetricsChart         — Bar/line charts            │
│ ├─ SuggestionCard       — Individual recommendation  │
│ ├─ ComparisonChart      — Before/after delta         │
│ └─ BotConnectorForm     — Add external bot          │
│                                                       │
│ lib/ (src/lib/)                                      │
│ ├─ api.ts               — API client (httpx-like)   │
│ ├─ types.ts             — TypeScript types (synced) │
│ ├─ hooks.ts             — Custom React hooks        │
│ └─ utils.ts             — Formatting, parsing, etc.  │
│                                                       │
│ styles/ (src/styles/)                                │
│ ├─ global.css           — Tailwind + custom vars    │
│ └─ components.css       — Reusable patterns         │
│                                                       │
└──────────────────────────────────────────────────────┘
       │
       └──→ API calls to /api/... endpoints
            (handled by main app)
```

## Key Modules

### src/main.tsx
- Entry point for Vite
- Mounts React app to `<div id="root">`
- Imports global CSS

### src/App.tsx
- **React Router** setup with protected routes
- **ProjectContext** — Current project state
- **API Client** — Singleton httpx-like client
- Layout: Navbar + Sidebar + Page outlet
- Error boundary

### src/pages/

#### ProjectsPage
- List all workspaces
- Create new project
- Delete project
- Each row is clickable → navigate to ProjectPage

#### ProjectPage (Dashboard)
- Shows project details
- Tabs:
  1. **Documents** → DocumentsPage
  2. **Configurations** → RAGConfigPage
  3. **Test Sets** → TestSetPage
  4. **Experiments** → ExperimentListPage
  5. **Suggestions** → SuggestionsPage

#### DocumentsPage
- Upload .txt, .pdf, .docx (up to 50MB)
- Drag-drop upload
- List uploaded documents
- Delete document
- **Preview Chunks**: Show how document splits (before committing)
  - Select strategy (recursive, markdown, etc.)
  - Select chunk size / overlap
  - Show 10 sample chunks
  - Commit or adjust

#### RAGConfigPage
- Create/edit RAG configuration
- Fields:
  - Chunk Config (strategy + size)
  - Embedding Config (model, dense vs sparse)
  - Search Type (dense, sparse, hybrid)
  - LLM Model (with gateway support)
  - System Prompt
  - Response Mode (single-shot vs multi-step)
  - Top-K for retrieval
  - Custom Headers for API calls
- Preview config before save
- Reuse existing configs

#### TestSetPage
- **Test Generation**:
  - Select chunk config
  - Choose generation method:
    1. Auto-generate from chunks
    2. Auto-generate with personas (6 templates + custom)
  - Set testset size (1-400 questions)
  - Stream generation progress
- **Knowledge Graph**:
  - Build KG from chunks or documents
  - Set `overlap_max_nodes` (typical: 500)
  - Progress bar (polls backend every 2s)
  - View KG as graph (nodes = entities, edges = relations)
  - Delete KG
- **Question Management**:
  - List all questions
  - Filter by status (pending, approved, rejected, edited)
  - Mark as approved/rejected
  - Edit question or reference contexts
  - Bulk actions (approve all, reject all)
  - Export to CSV

#### ExperimentPage
- Select test set + RAG config (or external bot)
- Choose metrics (20+ options)
- Optional: Enable multi-LLM judge (2-5 judges)
- Start experiment → streams progress via EventSource
  - Updates: stage, metric, progress percentage
  - Display spinner + progress bar
- Once complete: redirect to ResultsPage

#### ResultsPage
- Per-question view:
  - Question text
  - Retrieved contexts (numbered list)
  - Bot's answer
  - Citations (if available)
  - Score for each metric
  - Color-coded: red (< 0.4), yellow (0.4-0.7), green (>= 0.7)
- Aggregate view:
  - Mean + std dev per metric
  - Bar chart of metric scores
  - Heatmap: questions vs metrics
- Filter:
  - By metric (show only low/medium/high scores)
  - By question (search)
- Actions:
  - Annotate (human rating: accurate, partial, inaccurate)
  - View judge verdicts (if multi-LLM enabled)
  - Export to CSV

#### SuggestionsPage
- List generated suggestions for experiment
- Each suggestion shows:
  - Issue (e.g., "Low context_recall")
  - Root cause
  - Recommendation (e.g., "Increase top_k from 5 to 10")
  - Confidence score
- Apply suggestion:
  - Creates new RAG config with change
  - Optionally runs new experiment
- Batch apply:
  - Select multiple suggestions
  - Apply all at once
  - Compare old vs new metrics

#### ComparisonPage
- Two-experiment comparison
- Metrics table:
  - Metric name | Old score | New score | Delta | % change
- Per-question comparison:
  - Questions where score improved/degraded/unchanged
- Line chart showing metric improvements

### src/components/

#### ProjectSelector
```tsx
<ProjectSelector 
  value={projectId} 
  onChange={setProjectId}
  projects={projects}
/>
```
- Dropdown showing all projects
- Quick-switch between workspaces

#### DocumentUploader
```tsx
<DocumentUploader 
  projectId={projectId}
  onUpload={refreshDocuments}
/>
```
- Drag-drop zone
- File picker
- Shows upload progress
- Validates file type + size
- Calls POST /api/projects/{p}/documents

#### ChunkPreview
```tsx
<ChunkPreview 
  chunks={chunks}
  selectedStrategy={strategy}
  onStrategyChange={setStrategy}
/>
```
- Shows 10 sample chunks
- Strategy dropdown
- Chunk size / overlap sliders
- Live preview updates
- "Commit" button to save config

#### ConfigEditor
- RAG config form builder
- Dropdown selects for all enum fields
- Text input for system prompt
- "Save" calls PUT /api/projects/{p}/rag-configs/{id}

#### ExperimentRunner
```tsx
<ExperimentRunner 
  testsetId={testsetId}
  ragConfigId={ragConfigId}
  selectedMetrics={metrics}
  onProgress={setProgress}
  onComplete={setExperimentId}
/>
```
- Form: testset + config + metrics
- Button: "Run Experiment"
- SSE listener: GET /api/projects/{p}/experiments/{id}/progress
- Shows progress bar + current metric
- Auto-redirects when complete

#### ResultsTable
```tsx
<ResultsTable 
  results={results}
  metrics={metrics}
  filterBy={filterValue}
/>
```
- Virtualized table (infinite scroll)
- Columns: Question, Answer, Metric Scores
- Sortable by metric score
- Color-coded cells
- Row click → expand to see contexts

#### MetricsChart
```tsx
<MetricsChart 
  metrics={metrics}
  scores={scores}
/>
```
- Bar chart: metric names vs mean score
- Error bars: std dev
- Color-coded: red/yellow/green
- Hover: show exact value

#### SuggestionCard
```tsx
<SuggestionCard 
  suggestion={suggestion}
  onApply={applySuggestion}
/>
```
- Title: issue + confidence
- Body: root cause + recommendation
- Button: "Apply" or "Learn more"

### src/lib/

#### api.ts (API Client)
```typescript
const client = new APIClient(baseURL: '/api')

// Async request wrapper with error handling
client.get('/projects')
client.post('/projects/{p}/experiments', payload)
client.put('/projects/{p}/rag-configs/{id}', payload)
client.delete('/projects/{p}/documents/{id}')

// SSE stream
client.stream('/projects/{p}/experiments/{id}/progress', 
  (event) => updateProgress(event))
```

**Features**:
- Global error handling (show toast on 4xx/5xx)
- Request/response logging
- Auth header injection (if `RAGAS_API_KEY` set)
- TypeScript generics for type-safe responses
- Automatic JSON serialization

#### types.ts (TypeScript Types)
- Synced from backend `app/models.py` via code generation
- All request/response types
- Enums for valid values
- Union types for discriminated variants

#### hooks.ts (Custom React Hooks)
```typescript
useProject()              // Get current project from context
useExperiment(id)         // Fetch experiment + cache
useResults(experimentId)  // Paginated results
useMetricsForExperiment(id) // Metric config
useSSEStream(url)         // SSE event listener
```

#### utils.ts
```typescript
formatScore(score: number) // "0.85 (85%)"
scoreToColor(score)        // "red" | "yellow" | "green"
formatDelta(delta: number) // "+0.15" or "-0.08"
exportToCSV(data)          // Download CSV file
debounce(fn, ms)           // Debounce function
```

### src/styles/

#### global.css
- Tailwind directives
- Custom CSS variables (colors, spacing, fonts)
- Form styling
- Animation classes
- Dark mode support (if needed)

## Data Flow Example: Run Experiment

```
Frontend:
  1. User selects testset + RAG config + metrics
  2. Click "Run Experiment"
  3. POST /api/projects/{p}/experiments
     {
       "testset_id": 5,
       "rag_config_id": 3,
       "metrics": ["faithfulness", "answer_relevancy", ...],
       "bot_config_id": null (use RAG) or 2 (use bot)
     }

Backend:
  4. Create experiment row
  5. Return {experiment_id: 10}

Frontend:
  6. Open EventSource: GET /api/projects/{p}/experiments/10/progress
  7. Render progress modal with spinner
  8. Receive SSE events:
     - {stage: "loading_testset", progress: 10}
     - {stage: "scoring_faithfulness", progress: 15}
     - {stage: "scoring_answer_relevancy", progress: 25}
     - {stage: "complete", progress: 100}

Backend:
  9. For each question:
     - Call RAG or bot
     - Score with all metrics
     - Store result
     - Emit SSE event with progress

Frontend:
  10. When progress === 100, close EventSource
  11. Redirect to /projects/{p}/experiments/10/results
  12. Fetch GET /api/projects/{p}/experiments/10/results
  13. Render results table + charts

User:
  14. View per-question scores
  15. Click "View Suggestions" → Fetch suggestions
  16. Select suggestion → Apply → Create new config → Re-run
```

## Build & Deployment

### Development
```bash
cd frontend
npm install
npm run dev      # Vite dev server on :5173
```

### Production
```bash
cd frontend
npm run build    # Outputs to dist/
npm run preview  # Test production build locally
```

**In docker-compose**:
```dockerfile
# Build frontend first
WORKDIR /app/frontend
RUN npm install && npm run build

# Copy dist to app static mount
RUN cp -r dist ../frontend/dist
```

## External Dependencies

- `react` — UI library
- `typescript` — Type safety
- `vite` — Build tool
- `react-router-dom` — Client-side routing
- `tailwindcss` — Styling
- `recharts` (or similar) — Charts
- `lucide-react` — Icon library
- `http-status-codes` — Status code constants

## Related Areas

- [Main App Architecture](./main.md) — API endpoints
- [CLAUDE.md](../../CLAUDE.md) — Quick reference
