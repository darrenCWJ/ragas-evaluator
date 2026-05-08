| [README](../README.md) | [Features Guide](FEATURES.md) |
|---|---|

# Tribunal — Feature Guide

What each feature does and the idea behind it.

---

## Project Management

**What it does:** Create isolated workspaces that contain all documents, configs, test sets, and experiments.

**Why:** Prevents cross-contamination between separate testing campaigns. You can run parallel evaluations for different bots or use cases without data overlap.

---

## Document Ingestion

**What it does:** Upload `.txt`, `.pdf`, and `.docx` files (up to 50 MB each). PDFs are parsed with pypdf; DOCX files with python-docx. Documents can be tagged with a "context label" for contextual prefix embedding.

**Why:** RAG systems need source material. Context labels let you enrich embeddings with document-level semantics (e.g., "HR Policy", "Technical Docs") so retrieval can distinguish between document types.

---

## Chunking Pipeline

**What it does:** Split documents into chunks using 6 strategies:

| Strategy | Description |
|----------|-------------|
| `recursive` | Recursive character splitting |
| `markdown` | Markdown-aware splitting (headers, code blocks) |
| `token` | Token-level splitting |
| `fixed_overlap` | Fixed window with configurable overlap |
| `parent_child` | Large parent chunks with smaller child chunks for retrieval |
| `semantic` | Embedding-based semantic boundary detection |

Supports a **2-step pipeline** where you chain two strategies sequentially (e.g., markdown split then recursive). Post-chunking quality filters (`filter_params`) remove chunks that are too short, too long, or below a minimum token count. Chunks can be previewed before committing.

**Why:** Chunk quality directly impacts retrieval. Different document types benefit from different strategies. The 2-step pipeline handles hierarchical content. Preview lets you validate before investing in embedding.

---

## Embedding & Vectorisation

**What it does:** Embed chunks using three embedding backends:

| Type | Provider |
|------|----------|
| `dense_openai` | OpenAI text-embedding-3-small (or configured model) |
| `dense_sentence_transformers` | Open-source SentenceTransformers models |
| `bm25_sparse` | BM25 keyword-based sparse embeddings |

**Contextual prefix embedding** — when a document has a context label, the label is prepended to chunk text before embedding (e.g., `[HR Policy] Vacation accrues at...`). This improves retrieval precision across multi-corpus document sets.

Chunks are stored in ChromaDB (dense) or a BM25 index (sparse). Hybrid search combines both with Reciprocal Rank Fusion (RRF).

**Why:** No single embedding approach works best for all content. Dense embeddings capture semantic meaning; BM25 captures exact keyword matches. Hybrid search combines both for better precision/recall tradeoffs. Contextual prefixes help when multiple document types are present.

---

## RAG Configuration

**What it does:** Bundle an embedding config, chunk config, search type, LLM model, system prompt, reranker, and response mode into a single named config. Two response modes:

- **single_shot** — standard single-turn retrieval + generation
- **multi_step** — iterative retrieval over multiple rounds; configurable `max_steps`

**Reranker** — an optional cross-encoder reranker applied after retrieval with a configurable `top_k` cutoff. Reranks the initial candidate list before passing context to the LLM.

Search types: `dense`, `sparse`, `hybrid`.

**Why:** RAG configs encapsulate the entire pipeline so you can test variations systematically. Multi-step mode handles complex queries that need iterative reasoning. Reranking improves precision when the initial retrieval set is noisy.

---

## Test Set Generation

**What it does:** Generate test questions from documents using LLM-based synthesis. Two generation paths:

- **Direct generation** (`fast_mode=true`) — produces questions immediately from chunks or documents without pre-building a knowledge graph. Fast, lower diversity.
- **KG-based generation** (`fast_mode=false`) — first builds a knowledge graph (entity/relationship extraction) from chunks or raw documents, then generates questions grounded in the graph. Slower but higher diversity and factual coverage.

Configurable `overlap_max_nodes` controls how many node pairs are sampled during KG traversal (higher = more question variety, O(n²) cost). Generation supports multiple personas, configurable query distribution, and adjustable test set size (1–400 questions).

Test sets can also be **uploaded** from CSV or JSON, including optional `sql_query` / `sql_column` fields for SQL evaluation scenarios. Questions go through an approval workflow: pending, approved, rejected, or edited.

**Why:** Reliable evaluation needs high-quality, diverse test sets. KG-based generation uses the graph as a structured source of truth, reducing repetition. The approval workflow lets you filter bad questions before they pollute experiment results.

---

## Knowledge Graph (KG) Worker

**What it does:** Builds a knowledge graph from project chunks or raw documents as a preparatory step for KG-based test generation. The graph stores entities, relationships, and community summaries. Building is offloaded to the optional **KG Worker** service (`worker/`) to avoid blocking the main app.

The worker exposes 5 endpoints:

| Endpoint | Description |
|----------|-------------|
| `POST /build-kg` | Start an async KG build (returns 202) |
| `GET /progress/{project_id}` | Poll build progress and stage |
| `DELETE /kg/{project_id}` | Delete a stored KG |
| `POST /clear-build/{project_id}` | Clear a stale build lock after a crash |
| `GET /health` | Health check |

KG source can be `chunks` (uses a specific chunk config) or `documents` (uses raw uploaded documents).

**KG visualization** — the main app exposes SSE endpoints that stream KG nodes and edges incrementally as they are extracted. The frontend renders the graph in real time using Sigma.js so you can inspect the knowledge structure being built.

**Why:** KG construction is memory-intensive and can take minutes for large document sets. Running it in a separate service prevents it from impacting the main app. Multiple worker instances can be deployed behind `KG_WORKER_URLS` for parallel builds across projects.

---

## Persona Management

**What it does:** Define user personas that shape how test questions are generated (tone, expertise level, query style). Two generation modes:

- **Fast persona generation** — LLM call directly from document summaries; quick.
- **Full persona generation** — uses the KG community structure to identify distinct user archetypes; higher quality.

Personas are saved per project and reused across test sets. Custom personas can be defined manually.

**Why:** Diverse personas produce questions that reflect how different user types actually interact with a bot, revealing failure modes that homogeneous test sets miss.

---

## Experiment Runner

**What it does:** Run a test set against either an internal RAG config or an external bot connector. Streams progress via Server-Sent Events (SSE). Computes metrics for each result and stores retrieved contexts alongside responses. Config is snapshotted for reproducibility. Parent–child experiment lineage is tracked.

**Why:** Experiments are the core evaluation primitive. Config snapshots ensure you can always reproduce or explain past results. Lineage tracks the optimisation journey.

---

## Evaluation Metrics (RAGAS + Custom)

**What it does:** Compute 20+ metrics across categories. All metric computation is async; metric results include per-question scores and aggregate statistics.

### RAG Metrics
| Metric | What it measures |
|--------|-----------------|
| `faithfulness` | Response alignment with source context |
| `answer_relevancy` | Answer pertinence to the question |
| `context_precision` | Retrieval accuracy |
| `context_recall` | Coverage of relevant context |
| `context_entities_recall` | Entity extraction completeness |
| `noise_sensitivity` | Robustness to irrelevant context |
| `response_groundedness` | Factual grounding in retrieved context |

### Natural Language Comparison
| Metric | What it measures |
|--------|-----------------|
| `semantic_similarity` | Embedding cosine similarity to reference answer |
| `non_llm_string_similarity` | Levenshtein / Hamming / Jaro distance |
| `factual_correctness` | Factual overlap with reference answer |
| `bleu_score` | N-gram precision |
| `rouge_score` | Recall-oriented n-gram overlap |
| `chrf_score` | Character n-gram F-score |
| `exact_match` | Exact string match |
| `string_presence` | Substring presence check |

### General Purpose
| Metric | What it measures |
|--------|-----------------|
| `aspect_critic` | Custom aspect evaluation (e.g. harmfulness, helpfulness) |
| `rubrics_score` | Rubric-based multi-dimensional scoring |
| `instance_rubrics` | Per-question rubric scoring |
| `summarization_score` | Summary quality evaluation |

### NVIDIA Metrics
| Metric | What it measures |
|--------|-----------------|
| `answer_accuracy` | Response correctness |
| `context_relevance` | Context appropriateness |

### SQL / Tabular Metrics
| Metric | What it measures |
|--------|-----------------|
| `datacompy_score` | SQL query result comparison |
| `sql_semantic_equivalence` | Semantic SQL query equivalence |

**Why:** Different metrics target different failure modes. Retrieval metrics tell you if the right context was found; generation metrics tell you if the LLM used that context correctly. String metrics give cheap baselines. LLM-as-judge metrics handle nuanced quality.

---

## Custom Metrics

**What it does:** Define project-specific metrics in 6 types:

| Type | Description |
|------|-------------|
| `integer_range` | LLM rates response on a numeric scale |
| `similarity` | Compare response against a reference string |
| `rubrics` | User-defined rubric descriptions for LLM scoring |
| `instance_rubrics` | Per-question rubric (rubric stored on each test case) |
| `criteria_judge` | LLM judges whether a criterion is met (binary) |
| `reference_judge` | LLM compares response to a reference answer |

Metric descriptions can be refined using LLM-powered suggestions before saving.

**Why:** Standard metrics don't capture every domain-specific concern. Custom metrics let you evaluate tone, helpfulness, domain accuracy, or compliance without code changes.

---

## Bot Connectors

**What it does:** Test external bots through a plugin architecture supporting 7 connector types:

| Connector | Description |
|-----------|-------------|
| `openai` | OpenAI API (GPT models) |
| `claude` | Anthropic Claude API |
| `deepseek` | DeepSeek API |
| `gemini` | Google Gemini API |
| `glean` | Glean enterprise search bot |
| `custom` | Arbitrary HTTP API with configurable auth and headers |
| `csv` | Import pre-collected responses from a CSV file |

All connectors normalise responses to a unified format (answer + citations). Optional "prompt for sources" mode injects citation instructions into each request.

**Why:** Different organisations use different bots. The connector framework lets you evaluate any bot with the same metrics and test sets, enabling apples-to-apples comparison. CSV upload lets you evaluate systems you can't connect to directly.

---

## Multi-LLM Judge

**What it does:** Run evaluation metrics across multiple LLM judges simultaneously (configurable count, default 3) rather than relying on a single model. Each judge scores independently using a randomised temperature within a configurable range. The system computes a **reliability score** based on inter-judge agreement. Results below the reliability threshold are flagged. Individual judge verdicts include chain-of-thought reasoning and **claim-level annotations** for full auditability.

**Why:** Single-judge evaluation is noisy — models have biases and blind spots. Running multiple judges and measuring agreement gives a confidence signal alongside the score. High variance reveals genuinely ambiguous cases that need human review; high agreement gives stronger confidence in the score.

---

## Source Verification

**What it does:** After an experiment, verify bot-cited URLs by checking reachability and whether the page content actually supports the cited claim. Each citation receives a status:

| Status | Meaning |
|--------|---------|
| `verified` | URL is reachable and content supports the claim |
| `hallucinated` | URL is reachable but content does not support the claim |
| `inaccessible` | URL could not be fetched (404, timeout, etc.) |
| `unverifiable` | URL is present but content cannot be evaluated |

**Why:** LLMs frequently hallucinate citations. Source verification catches invented URLs and misrepresented sources, which is critical for production RAG systems where users trust cited links.

---

## Human Annotation & Evaluator Accuracy

**What it does:** Sample 20% of experiment results (deterministic seed) for human review. Reviewers rate each response as accurate, partially accurate, or inaccurate. The system then computes agreement between human ratings and automated metric scores to produce an **evaluator accuracy** percentage.

**Why:** Automated metrics aren't perfect. Human annotation provides ground truth to validate whether the metric suite is actually reliable. Low agreement reveals biased or poorly-calibrated metrics that need adjustment.

---

## Suggestion Engine

**What it does:** Analyse completed experiment results and generate actionable recommendations. Rule-based checks map low metric scores to specific diagnoses and config changes:

| Signal | Diagnosis | Suggestion |
|--------|-----------|------------|
| Low `context_recall` | Retrieval misses relevant chunks | Increase `top_k` or switch to hybrid search |
| Low `context_precision` | Too much irrelevant context retrieved | Decrease `top_k` or add reranking |
| Low `faithfulness` | LLM hallucinating beyond context | Strengthen system prompt grounding instructions |
| Low `answer_relevancy` | Responses drift from the question | Enable multi-step retrieval mode |
| Both recall and precision low | Embedding model mismatch | Switch embedding model |
| High metric variance | Inconsistent chunk quality | Try a different chunking strategy |

Suggestions can be applied individually or in batch to create a new experiment config directly from the UI.

**Why:** Users often don't know where to focus optimisation. The suggestion engine identifies the highest-impact changes and proposes concrete adjustments, enabling an iterative improvement loop: run experiment → get suggestions → apply → run again.

---

## External Baselines

**What it does:** Upload a CSV of reference Q&A pairs from an existing system (legacy bot, vendor, or human-written answers). Stored per project for comparison against experiment results.

**Why:** You need a benchmark to know if your changes are improvements. Baselines provide that context, whether it's comparing against a legacy system or a human gold standard.

---

## Experiment Comparison & Reporting

**What it does:** Compare two experiments with per-metric deltas (absolute and percentage change) and per-question differences. Track experiment lineage (parent–child relationships from suggestion application). Generate project-level reports aggregating metrics across experiments by bot type. Export results to CSV or JSON.

**Why:** Single experiment numbers aren't actionable without context. Deltas show whether changes helped. Lineage tracks the optimisation journey. Reports give executive-level summaries of overall progress.

---

## API Configuration

**What it does:** Configure custom HTTP endpoints per project with URL, API key, and custom headers for use with the `custom` bot connector.

**Why:** Organisations have proprietary APIs that aren't covered by built-in connectors. This allows adding them without code changes.

---

## KG Visualization

**What it does:** Stream knowledge graph nodes and edges via SSE as the KG is built. The frontend renders the graph incrementally using Sigma.js with force-directed layout, allowing you to inspect entities, relationships, and community structure in real time.

**Why:** Understanding what entities and relationships the KG has extracted helps diagnose test generation quality — if the graph misses key concepts, the generated questions will too.
