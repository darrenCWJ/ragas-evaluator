# Worker Service Codemap

**Last Updated:** 2026-06-13  
**Entry Points:** worker/main.py, worker/routes.py  
**Primary Purpose:** Offload memory-intensive KG construction and persona generation from the main application

## Architecture

The worker is a standalone FastAPI process. It reuses the root-level config.py, db/init.py,
evaluation/metrics/testgen.py, and pipeline/ directly -- no forked copies. Before the refactor
those modules lived under worker/; the copies drifted silently. They were removed entirely.

Both services share one database (SQLite or PostgreSQL). Shared module imports resolve from the
repo root because the Docker build context is the repo root and WORKDIR is /app.

    Main App (app/)                              KG Worker Service
    -----------------------------------------------------------------
    testsets.py
      POST /build-kg          --HTTP-->          POST /build-kg
      GET  /kg-progress       --HTTP-->          GET  /progress/{id}
      DELETE /kg/{id}         --HTTP-->          DELETE /kg/{id}
    personas.py               --HTTP-->          POST /generate-personas
                                                 GET  /persona-progress/{id}
    experiments.py            --HTTP-->      [/run-experiment  -- NOT IMPLEMENTED]
    testsets.py               --HTTP-->      [/run-testgen     -- NOT IMPLEMENTED]
    health.py                 --HTTP-->          GET  /health
                                                 GET  /status
    app/__init__.py            async             worker_monitor task

## Key Files

| File | Role | Importance |
|------|------|------------|
| worker/main.py | FastAPI factory, lifespan, CORS | Entry point |
| worker/routes.py | All endpoints, thread dispatch, in-memory state | Core logic |
| worker/Dockerfile | Repo-root build context; copies shared modules | Deployment |
| worker/requirements.txt | Pinned deps (must sync with root) | Dependency |
| config.py (ROOT) | Concurrency limits, timeouts, KG_WORKER_URLS | Shared config |
| db/init.py (ROOT) | SQLite/PostgreSQL connection, schema init | Shared DB |
| evaluation/metrics/testgen.py (ROOT) | KG builders, persona gen, progress | Business logic |

## Endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| GET | /health | 200 | Liveness: status, RSS MB (Unix only), active KG build count |
| GET | /status | 200 | Dashboard: all active tasks, RSS MB, concurrency limits |
| POST | /build-kg | 202 | Start async KG build; 409 duplicate, 503 at capacity |
| GET | /progress/{project_id} | 200 | KG build progress (query param kg_source, default: chunks) |
| DELETE | /kg/{project_id} | 204 | Delete KG from DB (query param kg_source) |
| POST | /clear-build/{project_id} | 200 | Clear stale KG lock and progress after crash |
| POST | /generate-personas | 202 | Start async persona generation; 409 duplicate, 503 at capacity |
| GET | /persona-progress/{project_id} | 200 | Persona status; returns personas list on completion |
| POST | /clear-personas/{project_id} | 200 | Clear stuck persona lock and progress |

## worker/main.py

Minimal FastAPI factory (39 lines). The lifespan handler runs db.init.init_db():

    import db.init
    db.init.init_db()

The db import resolves to the ROOT db/init.py -- there is no worker/db/ subdirectory.
CORS origins are read from CORS_ORIGINS env var (defaults to *). Router is worker.routes.router.

## worker/routes.py

### Concurrency guards

Limits are imported from the root config.py:

    from config import MAX_CONCURRENT_KG_BUILDS, MAX_CONCURRENT_PERSONA_BUILDS

- MAX_CONCURRENT_KG_BUILDS (default 1) -- checked via len(_active_builds) >= limit
- MAX_CONCURRENT_PERSONA_BUILDS (default 2) -- checked via count of entries with status generating

Both subsystems use a threading.Lock for atomic read-modify-write on their state dicts.

### Thread-based execution with fresh event loops

Both KG builds and persona generation run in daemon threads (threading.Thread(..., daemon=True)).
Each thread calls asyncio.new_event_loop() and asyncio.set_event_loop(loop) because the ragas
library uses async internals and the FastAPI event loop is already occupied. The loop is closed
in the finally block after every run.

## Shared-Module Architecture

The Dockerfile copies the following paths from the repo root into /app/:

    config.py   db/   evaluation/   pipeline/   worker/

The correct build invocation is:

    docker build -f worker/Dockerfile .    # context = repo root, NOT ./worker

Any change to config, db schema, or testgen logic is available to both services with one edit.
There is one source of truth.

Running the worker natively on Windows is unsupported: the resource module (used in /health,
/status, and testgen._log_memory) is Unix-only. Both endpoints wrap the import in try/except
and return rss_mb: null where unavailable. Use Docker (Linux container) in all environments.

## Execution Flows

### 1. KG Build

    Main app POST /testsets/build-kg:
      Pre-check workers for active build  (prevents duplicate after app restart)
      Try KG_WORKER_URLS in order:
        202 -> delegated; record _project_worker[key] = worker_url
        409 -> already in progress on that worker
        503 -> at capacity, try next worker
        err -> unreachable, try next worker
      All workers fail -> in-process fallback (thread or subprocess)

    Worker POST /build-kg:
      Lock _kg_lock
      409 if (project_id, kg_source) already in _active_builds
      503 if len(_active_builds) >= MAX_CONCURRENT_KG_BUILDS
      _active_builds[(project_id, kg_source)] = True
      Spawn daemon thread -> _run_kg_in_thread()

    Thread _run_kg_in_thread():
      asyncio.new_event_loop(); asyncio.set_event_loop(loop)
      set_progress(project_id, {stage: building_knowledge_graph}, kg_source)
      kg_source=documents -> build_kg_standalone_from_documents()
      kg_source=chunks    -> build_kg_standalone(chunk_config_id, ...)
        -> build_knowledge_graph()
             -> _apply_transform_batched()
                  per batch: _release_memory() + _log_memory() + sub-checkpoint
      success/exception: clear_progress()
      finally: loop.close(); _active_builds.pop(key)

### 2. KG Progress Polling

    Main app GET /kg-progress?project_id=N:
      GET {worker}/progress/N?kg_source=chunks

    Worker GET /progress/{project_id}:
      active   = _active_builds.get((id, source))
      progress = get_progress(id, kg_source)     # in-memory dict in testgen.py
      active=True  -> {active:true, stage, batch_current, nodes_processed, ...}
      active=False, KG in DB -> {active:false, status:completed|partial, ...}
      active=False, no KG    -> {active:false}

### 3. Persona Generation

    Main app POST /personas/generate:
      POST {worker}/generate-personas {project_id, chunk_config_id, num_personas}

    Worker POST /generate-personas:
      Lock _persona_lock
      409 if project_id status is generating
      503 if active count >= MAX_CONCURRENT_PERSONA_BUILDS
      _active_persona_builds[pid] = {status:generating, started_at, ...}
      Spawn daemon thread -> _run_personas_in_thread()

    Thread _run_personas_in_thread():
      asyncio.new_event_loop()
      set_progress(pid, {stage:generating_personas}, kg_source=personas)
      db.init.get_db().execute(SELECT content FROM chunks WHERE chunk_config_id=?)
      generate_personas(chunks, num_personas) + _enrich_with_question_styles()
      INSERT INTO personas + commit()
      success:   _active_persona_builds[pid] = {status:completed, result:[...]}
      exception: _active_persona_builds[pid] = {status:error, detail:...}
      finally: clear_progress(kg_source=personas); loop.close()

    GET /persona-progress/{project_id}:
      status generating -> {active:true, stage, ...}
      status completed  -> pop entry, return {active:false, personas:[...]}
      status error      -> pop entry, return {active:false, status:error, ...}
      not found         -> {active:false}

### 4. In-Process Fallback (No Worker Configured)

When KG_WORKER_URLS is empty, app/routes/testsets.py handles builds locally:

    KG_THREAD_MODE=true  -> spawn thread in main process (identical code path)
    KG_THREAD_MODE=false -> _run_kg_subprocess()
      env KG_PROGRESS_PIPE=1 passed to child
      testgen.set_progress / update_progress print JSON lines to stdout
      parent reads stdout and populates in-memory progress store
      KG_SUBPROCESS_TIMEOUT    -> SIGKILL child after N seconds (default 24 h)
      KG_SUBPROCESS_MAX_RSS_MB -> RLIMIT_AS via preexec_fn (Linux only)

## Memory Design

| Mechanism | Location | Purpose |
|-----------|----------|---------|
| _log_memory(label) | testgen.py:108 | Log RSS MB after each batch; no-op on Windows |
| _release_memory() | testgen.py:124 | gc.collect() + malloc_trim(0) (Linux) after every transform batch |
| Sub-checkpoints | build_knowledge_graph() | save_partial_fn(kg) after each batch; hard kill loses only current batch |
| KG_SUBPROCESS_MAX_RSS_MB | config.py:69 | RLIMIT_AS for subprocess builds; 0 = no limit; Linux only |

Progress state is a module-level _progress dict in testgen.py keyed (project_id, kg_source).
The worker reads it directly (same process). Subprocess builds relay it via KG_PROGRESS_PIPE JSON
lines printed to stdout.

## Configuration Reference (root config.py)

| Variable | Default | Description |
|----------|---------|-------------|
| MAX_CONCURRENT_KG_BUILDS | 1 | Max simultaneous KG builds per worker instance |
| MAX_CONCURRENT_PERSONA_BUILDS | 2 | Max simultaneous persona builds per worker instance |
| KG_SUBPROCESS_TIMEOUT | 86400 s | Hard kill timeout; set to 0 to disable |
| KG_SUBPROCESS_MAX_RSS_MB | 0 | RSS cap for subprocess builds (Linux; 0 = unlimited) |
| KG_BATCH_SIZE | 50 | Nodes per transform batch |
| KG_WORKER_URLS | empty | Comma-separated worker base URLs; empty = in-process fallback |
| KG_THREAD_MODE | false | Use thread (vs subprocess) for in-process fallback |
| DATABASE_URL | empty | PostgreSQL DSN; empty = SQLite at DATABASE_PATH |
| DATABASE_PATH | data/ragas.db | SQLite path resolved from repo root |

## Honest Limitations

1. /run-experiment and /run-testgen do not exist here.
   app/routes/experiments.py attempts POST {worker}/run-experiment and
   app/routes/testsets.py attempts POST {worker}/run-testgen when KG_WORKER_URLS is set.
   Both endpoints are absent. The main app receives 404 and silently falls back to local execution;
   no error is surfaced to the user.

2. Worker-experiment monitor polls a non-existent endpoint.
   The _monitor_worker_experiments coroutine in app/__init__.py polls
   {worker}/experiment-progress/{eid}. That route is not implemented here. After three consecutive
   failures it marks the experiment failed in the DB.

3. resource module is Unix-only.
   /health and /status wrap the import in try/except; rss_mb is null where unavailable.
   testgen._log_memory returns 0.0 on Windows. The worker is not runnable natively on Windows --
   use Docker (Linux container).

4. _active_persona_builds is in-memory only.
   A worker restart loses all in-flight entries. Clients polling /persona-progress/{id} receive
   {active: false} with no error and must treat that as a timeout/failure.

## Deployment

Dockerfile (key lines):

    FROM python:3.12-slim
    WORKDIR /app
    COPY worker/requirements.txt ./worker-requirements.txt
    RUN pip install --no-cache-dir -r worker-requirements.txt
    COPY config.py ./
    COPY db/ ./db/
    COPY evaluation/ ./evaluation/
    COPY pipeline/ ./pipeline/
    COPY worker/ ./worker/
    EXPOSE 3000
    CMD sh -c uvicorn worker.main:app --host 0.0.0.0 --port 3000  (PORT env var)

docker-compose.yml snippet:

    worker:
      build:
        context: .            # repo root, NOT ./worker
        dockerfile: worker/Dockerfile
      ports:
        - 3000:3000
      healthcheck:
        test: curl -f http://localhost:3000/health

Multiple instances are addressed via KG_WORKER_URLS. Each instance is stateless with respect to
the DB but stateful in-memory. Do not route the same build to two instances; each has its own
_active_builds dict and duplicate builds would both proceed.

## External Dependencies (worker/requirements.txt)

| Package | Purpose |
|---------|---------|
| fastapi>=0.115.0 | Web framework |
| uvicorn>=0.34.0 | ASGI server |
| python-dotenv>=1.2.0 | .env loading |
| ragas>=0.4.3 | KG extraction, persona generation |
| openai>=2.29.0 | LLM / embedding calls |
| anthropic>=0.42.0 | Claude LLM calls |
| psycopg2-binary>=2.9.0 | PostgreSQL driver |
| langchain-text-splitters>=0.3.0 | Chunking |
| chromadb>=0.6.0 | Vector store (transitive) |
| rapidfuzz>=3.0.0 | Fuzzy deduplication in testgen |

Pins must stay identical to root requirements.txt to avoid version skew between images.

## Related Areas

- docs/CODEMAPS/main.md -- Main app architecture and delegation logic
- CLAUDE.md -- Environment variables, run commands, integration notes