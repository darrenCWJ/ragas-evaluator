| [README](../README.md) | [Features Guide](FEATURES.md) |
|---|---|

# Feature Guide

What each feature does and the idea behind it.

---

## Project Management

**What it does:** Create isolated workspaces that contain all documents, configs, test sets, and experiments.

**Why:** Prevents cross-contamination between separate testing campaigns. You can run parallel evaluations for different bots or use cases without data overlap.

---

## Document Ingestion

**What it does:** Upload .txt and .pdf files (up to 50MB each). PDFs are parsed with pypdf. Documents can be tagged with a "context label" for contextual embeddings.

**Why:** RAG systems need source material. Context labels let you enrich embeddings with document-level semantics (e.g., "HR Policy", "Technical Docs") so retrieval can distinguish between document types.

---

## Chunking Pipeline

**What it does:** Split documents into chunks using 6 strategies: recursive, markdown, token, fixed overlap, parent-child, and semantic. Supports a 2-step pipeline (e.g., markdown first, then recursive) and post-chunking quality filters. Chunks can be previewed before committing.

**Why:** Chunk quality directly impacts retrieval. Different document types need different strategies. The 2-step pipeline handles hierarchical content (split by section, then by paragraph). Preview lets you validate before investing in embedding.

---

## Embedding & Vectorisation

**What it does:** Embed chunks using OpenAI dense embeddings, open-source sentence transformers, or BM25 sparse embeddings. Stored in ChromaDB. Supports hybrid search (dense + sparse with Reciprocal Rank Fusion).

**Why:** No single embedding approach works best for all content. Dense embeddings capture semantic meaning; BM25 captures exact keyword matches. Hybrid search combines both for better precision/recall tradeoffs.

---

## RAG Configuration

**What it does:** Bundle an embedding config, chunk config, search type, LLM model, system prompt, reranker, and response mode into a single config. Two response modes: single-shot (1-turn) and multi-step (iterative refinement, up to 10 steps).

**Why:** RAG configs encapsulate the entire pipeline so you can test variations systematically. Multi-step mode handles complex queries that need iterative reasoning and refinement.

---

## Test Set Generation

**What it does:** Generate test questions from documents using LLM-based synthesis. Two generation paths:

- **Direct generation** — produces questions immediately from chunks or documents without pre-building a knowledge graph. Fast, lower quality.
- **KG-based generation** — first builds a knowledge graph (entity/relationship extraction) from chunks or raw documents, then generates questions grounded in the graph. Slower but higher diversity and factual coverage.

Supports multiple personas (different user types), custom personas, query distribution control, and adjustable size (1–400 questions). Questions go through an approval workflow: pending, approved, rejected, edited.

**Why:** Reliable evaluation needs high-quality test sets. KG-based generation ensures factual grounding and reduces question repetition by using the graph as a structured source of truth. The approval workflow lets you filter out bad questions before they pollute experiment results.

---

## Knowledge Graph (KG) Worker

**What it does:** Builds a knowledge graph from project chunks or raw documents as a preparatory step for KG-based test generation. The graph stores entities, relationships, and community summaries. Building is offloaded to the optional **KG Worker** service (`worker/`) to avoid blocking the main app.

The worker exposes 5 endpoints:
| Endpoint | Description |
|---|---|
| `POST /build-kg` | Start an async KG build (returns 202) |
| `GET /progress/{project_id}` | Poll build progress and stage |
| `DELETE /kg/{project_id}` | Delete a stored KG |
| `POST /clear-build/{project_id}` | Clear a stale build lock after a crash |
| `GET /health` | Health check |

KG source can be `chunks` (uses a specific chunk config) or `documents` (uses raw uploaded documents).

**Why:** KG construction is memory-intensive and can take minutes for large document sets. Running it in a separate service prevents it from impacting the main app's responsiveness. Multiple worker instances can be deployed behind `KG_WORKER_URLS` for parallel builds across projects.

---

## Experiment Runner

**What it does:** Run a test set against either an internal RAG config or an external bot. Streams progress via Server-Sent Events. Computes metrics for each result and stores retrieved contexts alongside responses. Config is snapshotted for reproducibility.

**Why:** Experiments are the core evaluation primitive. They produce per-question metrics and aggregates for a given configuration. Config snapshots ensure you can always reproduce or explain past results.

---

## Evaluation Metrics (RAGAS + Custom)

**What it does:** Compute 20+ metrics across categories:

| Category | Metrics |
|----------|---------|
| Retrieval quality | context_precision, context_recall, context_relevance, context_entities_recall |
| Generation quality | faithfulness, answer_relevancy, factual_correctness, semantic_similarity |
| String-based | exact_match, string_presence, bleu_score, rouge_score, chrf_score |
| LLM-as-judge | aspect_critic, rubrics_score, answer_accuracy, response_groundedness |
| Other | noise_sensitivity, summarization_score |

**Why:** Different metrics target different failure modes. Retrieval metrics tell you if the right context was found; generation metrics tell you if the LLM used that context correctly. String metrics give quick, cheap baselines. LLM-as-judge metrics handle nuanced quality.

---

## Custom Metrics

**What it does:** Define project-specific metrics in 4 types: integer range (LLM rates on a scale), similarity (compare to reference), rubrics (user-defined rubric descriptions), and instance rubrics (per-question rubrics).

**Why:** Standard metrics don't capture every domain-specific concern. Custom metrics let you evaluate things like tone, helpfulness, domain accuracy, or compliance without changing code.

---

## Bot Connectors

**What it does:** Test external bots through a plugin architecture supporting 7 types: OpenAI, Claude, DeepSeek, Gemini, Glean, custom HTTP APIs, and CSV upload. All responses are normalised to a unified format (answer + citations). Optional "prompt for sources" mode injects citation instructions into the request.

**Why:** Different organisations use different bots. The connector framework lets you evaluate any bot with the same metrics and test sets, enabling apples-to-apples comparison without reimplementing evaluation logic. CSV upload lets you import pre-collected responses from systems you can't connect to directly.

---

## Multi-LLM Judge

**What it does:** Run evaluation metrics across multiple LLM judges simultaneously (configurable count, default 3) rather than relying on a single model. Each judge scores independently, and the system computes a reliability score based on inter-judge agreement. Results below the reliability threshold are flagged. Individual judge verdicts include chain-of-thought reasoning for auditability.

**Why:** Single-judge evaluation is noisy — different models have different biases and blind spots. Running multiple judges and measuring agreement gives a confidence signal alongside the score. High variance between judges reveals genuinely ambiguous or borderline cases that need human review, while high agreement gives stronger confidence in the score.

---

## Source Verification

**What it does:** After an experiment, verify bot-cited URLs by checking if each URL is reachable and whether the page content actually supports the claim. Each citation gets a status: verified, hallucinated, inaccessible, or unverifiable.

**Why:** LLMs frequently hallucinate citations (invented URLs, misrepresented sources). Source verification catches these errors, which is critical for production RAG systems where users trust cited sources.

---

## Human Annotation & Evaluator Accuracy

**What it does:** Sample 20% of experiment results (deterministic seed) for human review. Reviewers rate each response as accurate, partially accurate, or inaccurate. The system then computes agreement between human ratings and automated metric scores to produce an evaluator accuracy percentage.

**Why:** Automated metrics aren't perfect. Human annotation provides ground truth to validate whether the metric suite is actually reliable. Low agreement reveals biased or poorly-calibrated metrics that need adjustment.

---

## Suggestion Engine

**What it does:** Analyse completed experiment results and generate actionable recommendations. Rule-based checks identify issues (e.g., low context_recall suggests increasing top_k, low faithfulness suggests improving the system prompt). Suggestions can be applied individually or in batch to create a new experiment with the recommended config changes.

**Why:** Users often don't know where to focus optimisation. The suggestion engine identifies the highest-impact changes and proposes concrete config adjustments, enabling an iterative improvement loop: run experiment, get suggestions, apply, run again.

---

## External Baselines

**What it does:** Upload a CSV of reference Q&A pairs from an existing system (legacy bot, vendor, or human-written answers). Stored per project for comparison against experiment results.

**Why:** You need a benchmark to know if your changes are improvements. Baselines provide that context, whether it's comparing against a legacy system or a human gold standard.

---

## Experiment Comparison & Reporting

**What it does:** Compare two experiments with per-metric deltas (absolute and percentage change) and per-question differences. Track experiment lineage (parent-child relationships). Generate project-level reports aggregating metrics across experiments by bot type. Export results to CSV.

**Why:** Single experiment numbers aren't actionable without context. Deltas show whether changes helped. Lineage tracks the optimisation journey. Reports give executive-level summaries of overall progress.

---

## API Configuration

**What it does:** Configure custom HTTP endpoints per project with URL, API key, and custom headers.

**Why:** Organisations have proprietary APIs that aren't covered by built-in bot connectors. This allows adding them without code changes.
