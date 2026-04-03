# Ragas LLM Testing & Improvement Platform

> A self-hosted platform to build custom RAG bots, generate and annotate test questions, evaluate against multiple LLM models (OpenAI & Glean), and iteratively improve accuracy through structured experiments and actionable suggestions.

**Created:** 2026-03-31
**Last Updated:** 2026-03-31
**Type:** Application
**Stack:** Python + FastAPI + ChromaDB/Pinecone + SQLite + Docker + Railway
**Skill Loadout:** /paul:audit, /paul:plan
**Quality Gates:** test coverage, API contract validation, experiment reproducibility

---

## Problem Statement

Evaluating and improving LLM-powered RAG systems currently requires stitching together multiple tools — embedding pipelines, vector stores, evaluation frameworks, and manual comparison spreadsheets. There's no single place to build a RAG bot with configurable chunking and embedding strategies, generate test questions with human review, test against multiple LLM providers, run structured A/B experiments, and get actionable improvement suggestions.

This platform solves that for teams evaluating OpenAI models and Glean agents. The audience is developers and AI engineers who need to systematically test, compare, and improve their RAG pipelines with full control over retrieval strategy, response mode, and evaluation metrics.

Built on an existing foundation of 27 Ragas evaluation metrics already deployed with a web UI and API.

### Core Workflow

```
1. Upload docs → Build RAG bot (chunking + embedding + retrieval)
2. Generate test Q&A from those docs (ragas TestsetGenerator)
3. User reviews & annotates Q&A (approve / reject / edit answers)
4. Run approved Q&A against RAG bot AND Glean bot
5. Evaluate with ragas metrics → show results + improvement suggestions
6. User implements changes (re-chunk, re-embed, tweak prompts, etc.)
7. Re-run → compare → iterate
```

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | FastAPI (Python) | Already in use, async-native, strong ML ecosystem |
| Vector Store (Dev) | ChromaDB | Local, no account needed, fast dev loop |
| Vector Store (Prod) | Pinecone | Managed, scalable, supports hybrid search (dense + sparse) |
| Database | SQLite | File-based but queryable, supports experiment comparison, no server needed |
| Embeddings | OpenAI text-embedding-3-*, sentence-transformers, BM25 | Dense, sparse, and hybrid strategies |
| Evaluation | Ragas 0.4.3+ | Already integrated, 27 metrics, `@experiment` decorator |
| Test Generation | Ragas TestsetGenerator | Persona-based, pre-chunked data, custom query distributions |
| Frontend | HTML/CSS/JS (existing) → evolve as needed | Existing UI carries forward, enhance incrementally |
| Deployment | Docker → Railway | More compute than Vercel, supports long-running processes |

### Research Needed
- Glean API authentication and document collection retrieval endpoints
- Deep thinking RAG patterns (iterative retrieve-reason-retrieve)

---

## Data Model (SQLite)

### Schema

```sql
-- Projects
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Documents
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chunk Configurations
CREATE TABLE chunk_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    method TEXT NOT NULL,              -- 'recursive', 'parent_child', 'hierarchical'
    params_json TEXT NOT NULL,         -- {chunk_size, overlap, hierarchy_levels, etc.}
    step2_method TEXT,                 -- optional 2nd pass
    step2_params_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chunks
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_config_id INTEGER NOT NULL REFERENCES chunk_configs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    parent_chunk_id INTEGER REFERENCES chunks(id),
    embedding_blob BLOB,              -- stored embedding vector
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Embedding Configurations
CREATE TABLE embedding_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,                -- 'dense', 'bm25', 'hybrid'
    model_name TEXT,                   -- e.g. 'text-embedding-3-small'
    params_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Test Sets
CREATE TABLE test_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    generation_config_json TEXT,       -- {num_personas, query_distribution, etc.}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Test Questions (individual Q&A with annotation status)
CREATE TABLE test_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_set_id INTEGER NOT NULL REFERENCES test_sets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_contexts TEXT,           -- '||' delimited contexts used to generate
    question_type TEXT,                -- 'single_hop', 'multi_hop_abstract', 'multi_hop_specific'
    persona TEXT,                      -- persona name that generated this
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'approved', 'rejected', 'edited'
    user_edited_answer TEXT,           -- if user corrected the answer
    user_notes TEXT,                   -- optional annotation notes
    reviewed_at TIMESTAMP
);

-- Experiments
CREATE TABLE experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    test_set_id INTEGER NOT NULL REFERENCES test_sets(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    model TEXT NOT NULL,               -- 'gpt-4o', 'gpt-4o-mini', 'glean'
    model_params_json TEXT,            -- {temperature, top_k, response_mode, etc.}
    retrieval_config_json TEXT,        -- {strategy, top_k, reranking, etc.}
    chunk_config_id INTEGER REFERENCES chunk_configs(id),
    embedding_config_id INTEGER REFERENCES embedding_configs(id),
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'running', 'completed', 'failed'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Experiment Results (per-question scores)
CREATE TABLE experiment_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    test_question_id INTEGER NOT NULL REFERENCES test_questions(id),
    response TEXT,                     -- model's answer
    retrieved_contexts TEXT,           -- what was actually retrieved
    metrics_json TEXT NOT NULL,        -- {faithfulness: 0.9, context_recall: 0.7, ...}
    metadata_json TEXT,                -- {latency_ms, token_count, etc.}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Improvement Suggestions (generated after experiments)
CREATE TABLE suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    category TEXT NOT NULL,            -- 'retrieval', 'generation', 'chunking', 'embedding'
    signal TEXT NOT NULL,              -- 'low_context_recall', 'low_faithfulness', etc.
    suggestion TEXT NOT NULL,          -- human-readable recommendation
    priority TEXT NOT NULL DEFAULT 'medium',  -- 'high', 'medium', 'low'
    implemented BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Key Relationships
- A **Project** has many Documents, ChunkConfigs, EmbeddingConfigs, TestSets, Experiments
- A **TestSet** has many TestQuestions, each with annotation status (pending/approved/rejected/edited)
- An **Experiment** references a TestSet (uses only approved questions), a model, and optionally a chunk/embedding config
- **ExperimentResults** link back to individual TestQuestions for per-question analysis
- **Suggestions** are generated per-experiment based on metric patterns

---

## API Surface

### Auth Strategy
API key-based authentication (simple, sufficient for single-team use). Environment variable `API_KEY` checked on protected endpoints.

### Route Groups

| Group | Methods | Auth | Purpose |
|-------|---------|------|---------|
| /api/projects | GET, POST, DELETE | required | Create, list, delete projects |
| /api/documents | GET, POST, DELETE | required | Upload, list, delete documents |
| /api/documents/glean | GET, POST | required | Pull document collections from Glean |
| /api/chunking | POST, GET | required | Configure and execute chunking pipelines |
| /api/chunking/preview | POST | required | Preview chunks before committing |
| /api/embeddings | POST, GET | required | Configure embedding strategy, trigger embedding |
| /api/rag | POST | required | Query the RAG bot (single-shot or multi-step) |
| /api/testsets | GET, POST, DELETE | required | Create and manage test sets |
| /api/testsets/generate | POST | required | Generate test Q&A from project documents |
| /api/testsets/{id}/questions | GET, PUT | required | List questions, update annotation status |
| /api/testsets/{id}/questions/{qid}/annotate | PUT | required | Approve/reject/edit a single question |
| /api/experiments | GET, POST, DELETE | required | Create, list, run experiments |
| /api/experiments/{id}/results | GET | required | Fetch per-question experiment results |
| /api/experiments/{id}/suggestions | GET | required | Get improvement suggestions for an experiment |
| /api/experiments/compare | POST | required | Side-by-side comparison of experiments |
| /api/evaluate | POST | required | Existing single-query evaluation (27 metrics) |
| /api/metrics | GET | none | List available metrics |

### Internal vs External
- **Public endpoints:** /api/metrics (read-only metric list)
- **Protected endpoints:** Everything else (API key required)

---

## Deployment Strategy

### Local Development

| Service | Image/Runtime | Port | Purpose |
|---------|--------------|------|---------|
| app | python:3.11 | 8000 | FastAPI backend |
| (ChromaDB) | embedded in app | — | Vector storage (dev, runs in-process) |
| (SQLite) | embedded in app | — | Database (file: data/ragas.db) |

```yaml
# docker-compose.yml for local dev
services:
  app:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./:/app
      - ./data:/app/data    # SQLite + uploaded docs persist here
```

### Production (Railway)
- Single Docker container on Railway
- Environment variables: `OPENAI_API_KEY`, `PINECONE_API_KEY`, `GLEAN_API_KEY`, `API_KEY`, `VECTOR_STORE=pinecone`
- Railway auto-deploy from main branch
- 512MB+ RAM for embedding operations
- SQLite file persisted via Railway volume mount

---

## Security Considerations

- **Auth/Authz:** API key for all mutation endpoints. No multi-user/RBAC needed initially.
- **Input validation:** File upload type/size limits. Sanitize document content before chunking.
- **Secrets management:** All API keys via environment variables, never in code or responses.
- **Rate limiting:** Respect OpenAI and Glean API rate limits with backoff/retry.
- **Data handling:** Documents may contain sensitive content — no logging of document bodies.

---

## UI/UX Needs

### Design System
Extend existing dark theme (slate/indigo). Keep vanilla HTML/CSS/JS — add pages incrementally.

### Key Views / Pages

| View | Purpose | Complexity |
|------|---------|------------|
| Dashboard | Project overview, recent experiments, quick actions | Medium |
| RAG Builder | Upload docs, configure chunking + embedding, build pipeline | High — multi-step wizard |
| Test Set Generator | Generate questions, review personas, configure distribution | Medium |
| Annotation Review | Review generated Q&A, approve/reject/edit, bulk actions | Medium — table with inline editing |
| Experiment Lab | Configure experiment params, select model/mode, launch | High — parameterized forms |
| Results & Compare | Side-by-side results, metric charts, score bars, suggestions | High — data visualization |
| Evaluate (existing) | Current single-query evaluation — carries forward | Low — already built |

### Real-Time Requirements
- Experiment progress: SSE or polling for long-running experiment status
- Chunking/embedding progress: progress indicators for document processing
- Test generation progress: progress bar for question generation

### Responsive Needs
- Desktop-first (primary use case is dev/analysis workstation)

---

## Integration Points

| Integration | Type | Purpose | Auth |
|------------|------|---------|------|
| OpenAI API | REST API | LLM inference (GPT-4o, GPT-4o-mini, etc.) + embeddings | API key |
| Glean API | REST API | Query Glean agent + retrieve document collections | API key/OAuth |
| ChromaDB | Python lib | Vector storage for development (in-process) | N/A (local) |
| Pinecone | SDK | Vector storage for production (hybrid search) | API key |
| SQLite | Python stdlib | Experiment tracking, test sets, suggestions | N/A (local) |
| Ragas | Python lib | 27 evaluation metrics + `@experiment` decorator + TestsetGenerator | N/A (local) |
| sentence-transformers | Python lib | Alternative dense embeddings (local) | N/A (local) |
| rank_bm25 | Python lib | BM25 sparse keyword search | N/A (local) |

---

## Ragas API Reference (v0.4)

### `@experiment` Decorator

```python
from ragas import experiment, Dataset

@experiment()
async def my_experiment(row, model_name: str, temperature: float):
    response = await call_llm(row["query"], model=model_name, temperature=temperature)
    faith_score = faithfulness.score(response=response, contexts=row["contexts"])
    return {
        **row,
        "response": response,
        "faithfulness": faith_score.value,
    }

dataset = Dataset(name="my_test", backend="local/csv", root_dir="./evals")
results = await my_experiment.arun(dataset, name="run_1", model_name="gpt-4o", temperature=0.1)
```

- Decorator wraps async function, adds `.arun(dataset)` method
- Each row processed independently, results auto-saved
- Extra kwargs forwarded to the decorated function (enables A/B testing)
- `version_experiment()` for git-based run tracking

### TestsetGenerator

```python
from ragas.testset.synthesizers.generate import TestsetGenerator
from ragas.testset.persona import Persona, generate_personas_from_kg

generator = TestsetGenerator(llm=llm, embedding_model=embeddings, knowledge_graph=kg, persona_list=personas)

# From pre-chunked data (our primary path)
testset = generator.generate_with_chunks(chunks=text_chunks, testset_size=20)

# Custom query distribution
from ragas.testset.synthesizers.single_hop.specific import SingleHopSpecificQuerySynthesizer
query_distribution = [
    (SingleHopSpecificQuerySynthesizer(llm=llm, property_name="headlines"), 0.5),
    (SingleHopSpecificQuerySynthesizer(llm=llm, property_name="keyphrases"), 0.5),
]
testset = generator.generate(testset_size=20, query_distribution=query_distribution)

# Auto-generate personas from knowledge graph
personas = generate_personas_from_kg(kg=kg, llm=llm, num_personas=5)
```

- `generate_with_chunks()` accepts pre-chunked data (strings or LangChain Documents)
- Internally builds knowledge graph, extracts themes/keyphrases, generates personas
- Produces `Testset` with `.to_pandas()` for inspection

---

## Suggestion Engine Rules

The suggestion engine analyzes per-question metric scores after an experiment and generates actionable recommendations.

| Metric Signal | Category | Suggestion | Priority |
|--------------|----------|-----------|----------|
| Avg context_recall < 0.6 | retrieval | "Retrieval is missing relevant documents. Try hybrid search (dense + BM25), reduce chunk size, or increase top_k." | high |
| Avg context_precision < 0.6 | retrieval | "Too much irrelevant context retrieved. Reduce top_k, try re-ranking, or improve embedding model." | high |
| Avg faithfulness < 0.7 | generation | "Model is generating claims not supported by context. Try lower temperature, stricter system prompt, or a more capable model." | high |
| Avg answer_relevancy < 0.7 | generation | "Answers are drifting from the question. Refine the system prompt to stay focused on the query." | medium |
| Avg factual_correctness < 0.6 | generation | "Factual errors detected. Verify document quality, try a larger model, or add fact-checking step." | high |
| Avg semantic_similarity < 0.5 | generation | "Responses diverge significantly from reference answers. Check if the RAG bot has access to the right documents." | medium |
| Avg noise_sensitivity > 0.5 | retrieval | "Model is sensitive to irrelevant context. Filter retrieved chunks more aggressively or use re-ranking." | medium |
| Avg context_entities_recall < 0.5 | retrieval | "Key entities are missing from retrieved context. Try entity-aware chunking or knowledge graph augmentation." | medium |

Additional rules:
- If **both** context_recall and faithfulness are low → "Fundamental retrieval issue. Start by fixing retrieval before tuning generation."
- If context_recall is high but faithfulness is low → "Retrieval is good but the model hallucinates. Focus on generation constraints."
- Compare against previous experiment if available → "Context recall improved from 0.52 to 0.71 after switching to hybrid search."

---

## Phase Breakdown

### Phase 1: Docker + Railway Migration
- **Build:** Dockerfile, docker-compose.yml, Railway config. Migrate existing app from Vercel. Set up SQLite database initialization.
- **Testable:** App runs locally in Docker and deploys to Railway with all current features working. SQLite database created on first run.
- **Outcome:** Existing evaluation tool running on Railway with SQLite instead of Vercel with filesystem.

### Phase 2: Document Pipeline & Chunking Engine
- **Build:** Document upload API, project management, chunking engine (recursive, parent-child, hierarchical, overlap), 2-step chunking pipeline config, chunk preview endpoint.
- **Testable:** Create a project, upload PDF/TXT, configure chunking strategy, preview and commit chunks.
- **Outcome:** Documents processed and chunked with configurable strategies, stored in SQLite.

### Phase 3: Embedding & Vector Storage
- **Build:** Embedding engine (dense OpenAI, dense sentence-transformers, BM25 sparse, hybrid), vector store abstraction (ChromaDB for dev, Pinecone for prod), index management.
- **Testable:** Chunks embedded and stored in ChromaDB locally, basic similarity search works. Toggle to Pinecone via env var.
- **Outcome:** Full document-to-vector pipeline operational with selectable vector store.

### Phase 4: RAG Bot (Single-Shot & Multi-Step)
- **Build:** RAG query engine with single-shot and multi-step response modes. Retrieval → LLM generation pipeline. Multi-step: retrieve → reason → identify gaps → retrieve again → synthesize.
- **Testable:** Ask a question, get answer from RAG bot in both modes, see retrieved contexts.
- **Outcome:** Working RAG bot with configurable response mode.

### Phase 5: Test Set Generation & Annotation
- **Build:** Ragas `TestsetGenerator` integration using project's chunked documents. Persona generation (auto from knowledge graph + manual). Custom query distribution (single-hop, multi-hop). Annotation UI for reviewing generated Q&A — approve, reject, edit answers, add notes. Bulk actions (approve all, reject all).
- **Testable:** Generate 20 test questions from uploaded docs with 3 personas. Review in annotation UI, edit 5 answers, approve 15, reject 5. Only approved questions available for experiments.
- **Outcome:** Human-reviewed test sets ready for experimentation.
- **Built so far:** Test question generator module (`ragas_test/testgen.py`), basic API endpoints, web UI with paste/upload input. Needs refactoring to use new TestsetGenerator API and annotation workflow.

### Phase 6: Multi-Model Support & Experiment Runner
- **Build:** Model connector abstraction (OpenAI models + Glean agent). Ragas `@experiment` decorator integration. Experiment configuration UI (select model, response mode, retrieval params, test set). Experiment runner with progress tracking (SSE). Glean API integration for querying Glean agent. Glean document import for pulling document collections.
- **Testable:** Run same approved test set against GPT-4o RAG bot and Glean agent. Both experiments complete and results stored in SQLite.
- **Outcome:** Can test any supported model against the same human-reviewed test set.

### Phase 7: Results Dashboard & Improvement Suggestions
- **Build:** Per-experiment results view (per-question scores, response text, retrieved contexts). Side-by-side experiment comparison (same test set, different models/configs). Metric visualization (score bars, charts, deltas between runs). Suggestion engine — analyzes metric patterns and generates actionable recommendations. Historical experiment timeline per project.
- **Testable:** Compare GPT-4o vs Glean experiment. See that Glean has lower context_recall. Suggestion engine recommends "try hybrid search." User sees exactly which questions each model got wrong.
- **Outcome:** Complete visibility into what's working and what to improve.

### Phase 8: Feedback Loop & Iteration
- **Build:** Re-configure pipeline from suggestions (link suggestions to config changes). Re-run experiments with new config. Automatic delta comparison (new run vs previous). Track which suggestions were implemented and their impact. Export results (CSV, JSON).
- **Testable:** Implement "switch to hybrid search" suggestion. Re-run experiment. Dashboard shows context_recall improved from 0.52 to 0.71. Suggestion marked as implemented with measured impact.
- **Outcome:** Complete test → compare → suggest → improve → re-test workflow.

---

## Skill Loadout & Quality Gates

### Skills Used During Build

| Skill | When It Fires | Purpose |
|-------|--------------|---------|
| /paul:plan | Start of each phase | Detailed implementation planning |
| /paul:audit | End of each milestone | Architecture review |
| /paul:verify | End of each phase | UAT validation |

### Quality Gates

| Gate | Threshold | When |
|------|-----------|------|
| Test coverage | 70%+ | Each phase |
| API contract | All endpoints return expected schema | Each API phase |
| Experiment reproducibility | Same config → same results | Phase 6 |
| Docker build | Clean build, no warnings | Phase 1+ |
| Suggestion accuracy | Suggestions match known failure patterns | Phase 7 |

---

## Design Decisions

1. **ChromaDB for dev, Pinecone for prod**: ChromaDB runs in-process with no account needed — fast dev loop. Pinecone for production scalability and hybrid search. Vector store abstracted behind a common interface so switching is a config change.
2. **SQLite over filesystem**: Experiment comparison requires filtering, joining, and aggregation. SQLite is file-based (no server) but gives full SQL query power. Stored at `data/ragas.db`.
3. **Human-in-the-loop annotation before testing**: Generated test Q&A may have incorrect reference answers. User review ensures test accuracy before using questions to evaluate models. Without this, bad reference answers produce misleading metric scores.
4. **Test sets shared across models**: Same approved test set runs against both RAG bot and Glean — ensures fair comparison on identical questions.
5. **Suggestion engine as rules, not ML**: Metric-to-suggestion mapping is deterministic based on score thresholds. Simple, explainable, and doesn't require training data. Can evolve to LLM-powered analysis later.
6. **2-step chunking pipeline**: Allows combining strategies (e.g., hierarchical first pass → overlap refinement) for optimal retrieval quality.
7. **Single-shot and multi-step as experiment parameters**: Rather than separate systems, response mode is a configurable parameter — enables direct comparison.
8. **Docker over serverless**: RAG bot building requires sustained compute, large file handling, and long-running processes that don't fit serverless constraints.
9. **Extend existing UI incrementally**: No framework rewrite — add pages to the existing vanilla HTML/CSS/JS. Migrate to a framework only if complexity demands it.

---

## Open Questions

1. What Glean API endpoints are available for document collection retrieval? (Need API docs access)
2. What's the maximum document size / collection size to support?
3. Should multi-step RAG have a configurable max iterations, or fixed at 2-3 steps?
4. Should the suggestion engine use LLM analysis for nuanced recommendations, or keep it rule-based?

---

## Next Actions

- [ ] `/seed launch ragas-platform` or `/paul:init` to begin Phase 1
- [ ] Obtain Glean API documentation and credentials
- [ ] Set up Pinecone account and index (needed for Phase 3 prod path)

---

## References

- [Ragas Experimentation Docs](https://docs.ragas.io/en/stable/concepts/experimentation/)
- [Ragas TestsetGenerator — Persona Generator](https://docs.ragas.io/en/stable/howtos/customizations/testgenerator/_persona_generator/)
- [Ragas TestsetGenerator — Pre-chunked Data](https://docs.ragas.io/en/stable/howtos/customizations/testgenerator/prechunked_data/)
- [Ragas TestsetGenerator — Customisation](https://docs.ragas.io/en/stable/howtos/customizations/testgenerator/_testgen-customisation/)
- [Ragas TestsetGenerator — Custom Single-Hop](https://docs.ragas.io/en/stable/howtos/customizations/testgenerator/_testgen-custom-single-hop/)
- [Ragas — Evaluate and Improve RAG](https://docs.ragas.io/en/stable/howtos/applications/evaluate-and-improve-rag/)
- [Ragas Migration v0.3 → v0.4](https://docs.ragas.io/en/stable/howtos/migrations/migrate_from_v03_to_v04/)
- [Pinecone Hybrid Search](https://docs.pinecone.io/guides/data/understanding-hybrid-search)
- Existing codebase: 27 metrics in `ragas_test/`, web UI in `public/index.html`, API in `api/evaluate.py`

---

*Last updated: 2026-03-31*
