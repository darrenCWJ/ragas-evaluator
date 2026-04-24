# Worker Service Codemap

**Last Updated:** 2026-04-24  
**Entry Points:** `worker/main.py`, `worker/routes.py`  
**Primary Purpose:** Offload memory-intensive knowledge graph (KG) construction from main application

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     KG Worker Service                        │
│                 (Separate FastAPI Process)                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  worker/main.py                                              │
│  └─ FastAPI app with lifespan handler                        │
│     └─ Initializes worker DB via worker/db/init.py           │
│                                                               │
│  worker/routes.py (5 async endpoints)                        │
│  ├─ GET  /health                                             │
│  ├─ POST /build-kg (async, 202 Accepted)                     │
│  ├─ GET  /progress/{project_id}                              │
│  ├─ DELETE /kg/{project_id}                                  │
│  └─ POST /clear-build/{project_id}                           │
│                                                               │
│  worker/config.py                                            │
│  └─ Env-driven config: timeouts, concurrency, paths          │
│                                                               │
│  worker/db/init.py (595 lines)                               │
│  └─ KG schema: knowledge_graphs, kg_entities, kg_edges,      │
│     kg_metadata, kg_build_progress                           │
│                                                               │
│  worker/evaluation/metrics/testgen.py (2630 lines)           │
│  └─ KG builders: build_kg_standalone(),                      │
│     build_kg_standalone_from_documents(),                    │
│     progress tracking, metadata storage                      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
         ▲                                    │
         │                                    │ HTTP
         │                                    │
  Shared │                                    ▼
Database │                   ┌─────────────────────────────────┐
  (PG/  │                   │       Main App (app/)             │
  SQLite)│                   │  app/routes/testsets.py          │
         │                   │  ├─ POST /build-kg              │
         │                   │  │  (delegates to worker)       │
         │                   │  ├─ GET /testset-progress       │
         │                   │  │  (polls /progress/{id})      │
         │                   │  └─ GET /kg/status              │
         │                   │     (queries shared DB)         │
         │                   └─────────────────────────────────┘
         └───────────────────────────────────────────────────────
```

## Key Modules

### worker/main.py (39 lines)
- **Purpose**: FastAPI application factory
- **Lifespan**: Calls `db.init.init_db()` on startup
- **CORS**: Configurable via `CORS_ORIGINS` env var
- **Router**: Includes routes from `worker/routes.py`

### worker/routes.py (124 lines)
- **State Management**:
  - `_kg_lock` (threading.Lock) — thread-safe access
  - `_active_builds` dict — tracks (project_id, kg_source) → bool
- **Endpoints**:
  1. `GET /health` — Simple liveness check
  2. `POST /build-kg` — Start async KG build (request: `BuildKGRequest`)
     - Returns 202 Accepted with status
     - Returns 409 if build already in progress
     - Returns 503 if worker busy (>= `MAX_CONCURRENT_KG_BUILDS`)
  3. `GET /progress/{project_id}` — Poll build progress
     - Returns active build state and progress from DB
     - Query param: `kg_source` (default: "chunks")
  4. `DELETE /kg/{project_id}` — Delete KG from DB
  5. `POST /clear-build/{project_id}` — Clear stale locks
- **Threading Model**:
  - Builds run in daemon threads via `_run_kg_in_thread()`
  - Each thread creates its own event loop
  - Progress written to shared database in real time

### worker/config.py (132 lines)
- **Storage Paths**:
  - `DATABASE_URL` — PostgreSQL or empty for SQLite
  - `DATABASE_PATH` — SQLite path (default: data/ragas.db)
  - `CHROMADB_PATH`, `BM25_PATH` — Embedding indices
- **KG-Specific**:
  - `MAX_CONCURRENT_KG_BUILDS` (default: 1) — Concurrency limit
  - `KG_SUBPROCESS_TIMEOUT` (default: 86400 = 24h) — Build timeout
  - `KG_BATCH_SIZE` (default: 50) — Entity processing batch size
- **LLM Config**:
  - `DEFAULT_EVAL_MODEL`, `DEFAULT_EVAL_EMBEDDING`
  - `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`
- **Shared with Main App**:
  - Timeouts, model defaults, validation sets

### worker/db/init.py (595 lines)
- **Schema** (main tables):
  - `knowledge_graphs` — (id, project_id, kg_source, chunk_config_id, is_complete, created_at)
  - `kg_entities` — (id, kg_id, name, embedding, metadata_json)
  - `kg_edges` — (id, kg_id, source_id, target_id, relation, metadata_json)
  - `kg_metadata` — (kg_id, key, value) — stores build progress
  - `kg_build_progress` — (project_id, kg_source, stage, percentage, error_msg, updated_at)
- **Connection Model**:
  - Module-level `_connection` (sqlite3.Connection or psycopg2 cursor)
  - All queries go through functions in this module
  - `init_db()` called by lifespan handler
- **Key Functions**:
  - `get_kg_info(project_id, kg_source)` — Fetch KG metadata
  - `set_kg_progress(project_id, kg_source, stage, percentage)` — Update progress
  - `delete_kg_from_db(project_id, kg_source)` — Remove KG

### worker/evaluation/metrics/testgen.py (2630 lines)
- **Purpose**: Core KG building logic (shared with main app)
- **Main Functions**:
  - `build_kg_standalone(chunk_config_id, project_id, overlap_max_nodes, fast_mode)`
    - Fetch chunks from DB
    - Build knowledge graph via Ragas
    - Save entities and edges to DB
    - Update progress in real time
  - `build_kg_standalone_from_documents(project_id, overlap_max_nodes)`
    - Alternative: build KG directly from documents
  - `set_progress(project_id, data, kg_source)` — Store progress in DB
  - `get_progress(project_id, kg_source)` — Fetch current progress
  - `get_kg_info(project_id, kg_source)` — Fetch KG metadata
  - `delete_kg_from_db(project_id, kg_source)` — Delete KG
- **Progress Tracking**:
  - Stages: "building_knowledge_graph", "validating", "complete"
  - Percentage: 0-100
  - Stored in `kg_metadata` table for persistence
- **Algorithm**:
  - Group chunks by document
  - Extract entities and relations via Ragas
  - Deduplicate and rank by importance
  - Handle overlaps via `overlap_max_nodes` parameter
  - Fast mode: skip validation steps

## Data Flow

### 1. Start KG Build (Main App → Worker)

```
Main app: POST /testsets/build-kg
├─ Check if build in progress
├─ Try KG_WORKER_URLS in order (load balancing)
└─ POST {worker_url}/build-kg with BuildKGRequest
   {
     "project_id": 123,
     "chunk_config_id": 45,
     "kg_source": "chunks",
     "overlap_max_nodes": 500,
     "fast_mode": false
   }

Worker: POST /build-kg
├─ Check 409 (build in progress)
├─ Check 503 (worker busy)
├─ Lock _kg_lock
├─ Add to _active_builds[(project_id, kg_source)]
└─ Spawn daemon thread: _run_kg_in_thread()

Background Thread:
├─ Create event loop
├─ Call build_kg_standalone() or build_kg_standalone_from_documents()
├─ Write progress to DB periodically
├─ Handle exceptions and log
└─ Remove from _active_builds and close loop
```

### 2. Poll Progress (Main App ← Worker)

```
Main app: GET /testset-progress?project_id=123&kg_source=chunks
├─ Try KG_WORKER_URLS in order
└─ GET {worker_url}/progress/123?kg_source=chunks

Worker: GET /progress/{project_id}
├─ Check if (project_id, kg_source) in _active_builds
├─ If active: return progress from DB (stage, percentage, etc.)
└─ If not active: return KG info from DB (if built) or {}

Main App (Frontend):
├─ Receive {active: true, stage: "...", percentage: 50}
├─ Display progress bar
└─ Poll again every 2 seconds
```

### 3. Fallback (No Worker)

If `KG_WORKER_URLS` not set or all workers unreachable:

```
Main app: POST /testsets/build-kg
├─ KG_WORKER_URLS is empty
├─ Check KG_THREAD_MODE env var
│  ├─ If true: spawn thread in main process
│  └─ If false: use subprocess (slower, more isolated)
└─ Same progress tracking via DB polling
```

## Configuration Examples

### Single Worker (Development)

```bash
# .env
KG_WORKER_URL=http://localhost:3000
```

### Multiple Workers (Production)

```bash
# .env
KG_WORKER_URLS=http://kg-worker-1:3000,http://kg-worker-2:3000,http://kg-worker-3:3000
```

### No Worker (In-Process)

```bash
# .env (leave KG_WORKER_URLS unset)
KG_THREAD_MODE=true  # Use threads instead of subprocesses
```

## Deployment

### Docker Compose (Both Services)

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - worker

  worker:
    build:
      context: ./worker
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
```

### Kubernetes (Separate Deployment)

```yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kg-worker
spec:
  replicas: 2  # Scale horizontally
  template:
    spec:
      containers:
      - name: worker
        image: ragas-worker:latest
        ports:
        - containerPort: 3000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: connection-string
        - name: MAX_CONCURRENT_KG_BUILDS
          value: "1"
        livenessProbe:
          httpGet:
            path: /health
            port: 3000
          initialDelaySeconds: 10
          periodSeconds: 30
```

## External Dependencies

- `fastapi>=0.115.0` — Web framework
- `uvicorn>=0.34.0` — ASGI server
- `ragas>=0.4.3` — KG extraction library
- `langchain-text-splitters>=0.3.0` — Chunking (shared with main app)
- `chromadb>=0.6.0` — Vector store (shared with main app)
- `psycopg2-binary>=2.9.0` — PostgreSQL driver
- `openai>=2.29.0` — OpenAI API
- `anthropic>=0.42.0` — Anthropic API

## Related Areas

- [Main App Architecture](./main.md) — How main app delegates to worker
- [CLAUDE.md](../../CLAUDE.md) — Integration details, env vars, commands
- [README.md](../../README.md) — Project overview
