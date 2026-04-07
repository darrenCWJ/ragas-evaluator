| [README](README.md) | [Features Guide](docs/FEATURES.md) |
|---|---|

# RAG Evaluator

## Problem Statement

As AI chatbots become increasingly accessible, more individuals and teams are building conversational bots for customer support, internal knowledge bases, education, and other domains. However, a critical gap remains: **how do you know if your bot is actually giving accurate, grounded answers?**

Most RAG (Retrieval-Augmented Generation) systems are deployed with minimal evaluation. Builders rely on manual spot-checking or anecdotal feedback, leaving systemic issues — hallucinations, poor retrieval, irrelevant responses — undetected until users complain.

This project addresses that gap. It provides an **LLM-as-a-judge evaluation platform** that systematically tests a RAG pipeline, identifies where it falls short, and generates actionable suggestions to improve it.

## Design

### Core Idea

Rather than treating evaluation as a one-off check, the system enables an **iterative improvement loop**:

1. **Configure** a RAG pipeline (chunking strategy, embedding model, retrieval mode, LLM)
2. **Generate** synthetic test questions from your documents using diverse personas
3. **Run experiments** that evaluate every question against 20+ metrics
4. **Analyze results** with an AI-powered suggestion engine that pinpoints weak spots
5. **Apply suggestions** to create a new configuration and re-run — comparing before and after

### Architecture

```
                    +------------------+
                    |   React Web UI   |
                    +--------+---------+
                             |
                    +--------+---------+
                    |   FastAPI REST   |
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
  +-------+-------+  +------+------+  +--------+--------+
  |   Pipeline    |  |  Evaluation |  |    Database     |
  | chunking      |  | 20+ metrics |  | SQLite (WAL)   |
  | embedding     |  | scoring     |  | projects       |
  | retrieval     |  | suggestions |  | configs        |
  | generation    |  | test gen    |  | experiments    |
  +---------------+  +-------------+  +----------------+
```

### Suggestion Engine

The suggestion engine analyzes aggregate metric scores and per-question variance to produce targeted recommendations:

| Signal | Diagnosis | Suggestion |
|--------|-----------|------------|
| Low context recall | Retrieval misses relevant chunks | Increase `top_k` or switch to hybrid search |
| Low context precision | Too much irrelevant context retrieved | Decrease `top_k` or add reranking |
| Low faithfulness | LLM hallucinating beyond retrieved context | Strengthen system prompt grounding instructions |
| Low answer relevancy | Responses drift from the question | Enable multi-step retrieval mode |
| Both recall and precision low | Embedding model mismatch for the domain | Switch embedding model |
| High metric variance across questions | Inconsistent chunk quality | Try a different chunking strategy |

Each suggestion maps to a specific config field and can be applied directly from the UI to spawn a new experiment.

## Metrics

### RAG Metrics
| Metric | What it measures |
|---|---|
| `faithfulness` | Response alignment with source context |
| `answer_relevancy` | Answer pertinence to the question |
| `context_precision` | Retrieval accuracy |
| `context_recall` | Coverage of relevant context |
| `context_entities_recall` | Entity extraction completeness |
| `noise_sensitivity` | Robustness to irrelevant context |

### Natural Language Comparison
| Metric | What it measures |
|---|---|
| `semantic_similarity` | Embedding cosine similarity |
| `non_llm_string_similarity` | Levenshtein / Hamming / Jaro distance |
| `bleu_score` | N-gram precision |
| `rouge_score` | Recall-oriented n-gram overlap |
| `chrf_score` | Character n-gram F-score |
| `exact_match` | Exact string match |
| `string_presence` | Substring presence check |

### General Purpose
| Metric | What it measures |
|---|---|
| `aspect_critic` | Custom aspect evaluation (e.g. harmfulness) |
| `rubrics_score` | Rubric-based multi-dimensional scoring |
| `summarization_score` | Summary quality evaluation |

### NVIDIA Metrics
| Metric | What it measures |
|---|---|
| `answer_accuracy` | Response correctness |
| `context_relevance` | Context appropriateness |
| `response_groundedness` | Factual grounding in context |

### Agent Metrics
| Metric | What it measures |
|---|---|
| `topic_adherence` | Topic focus monitoring |
| `tool_call_accuracy` | Correct tool invocation |

### SQL Metrics
| Metric | What it measures |
|---|---|
| `datacompy_score` | SQL query result comparison |
| `sql_semantic_equivalence` | Semantic SQL query comparison |

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- OpenAI API key

### Backend

```bash
pip install -r requirements.txt
cp .env.example .env
# Add your OPENAI_API_KEY to .env
```

### Frontend

```bash
cd frontend
npm install
npm run build
```

### Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The app serves the built frontend as a SPA at `http://localhost:8000`.

### Docker

```bash
docker compose up --build
```

## Project Structure

```
├── app/                     # FastAPI application
│   ├── __init__.py          # App factory, middleware, lifespan
│   ├── models.py            # Pydantic request/response models
│   └── routes/              # Route modules
│       ├── projects.py      # Project CRUD
│       ├── documents.py     # Document upload (PDF/TXT)
│       ├── chunks.py        # Chunking configuration
│       ├── embeddings.py    # Embedding configuration
│       ├── rag.py           # RAG config and single-query testing
│       ├── testsets.py      # Test set generation and curation
│       ├── experiments.py   # Experiment runner (SSE streaming)
│       └── analyze.py       # Suggestions and config changes
├── pipeline/                # RAG engine
│   ├── chunking.py          # 4 chunking strategies
│   ├── embedding.py         # OpenAI + SentenceTransformers
│   ├── vectorstore.py       # ChromaDB integration
│   ├── bm25.py              # BM25 sparse search
│   ├── rag.py               # Retrieval + generation (dense/sparse/hybrid)
│   └── llm.py               # LLM provider routing
├── evaluation/              # Metrics and analysis
│   ├── metrics/             # 20+ metric modules
│   ├── scoring.py           # Metric orchestration
│   ├── suggestions.py       # Rule-based suggestion engine
│   └── testgen.py           # Synthetic test generation (Ragas)
├── db/                      # SQLite database layer
│   └── init.py              # Schema, migrations, queries
├── frontend/                # React + TypeScript + Tailwind SPA
│   └── src/
│       ├── pages/           # Setup, Build, Test, Experiment, Analyze
│       └── components/      # UI components per feature
├── tests/                   # pytest test suite
├── main.py                  # Uvicorn entrypoint
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Uvicorn |
| Database | SQLite (WAL mode) |
| LLM | OpenAI API (GPT-4o / GPT-4o Mini) |
| Evaluation | Ragas 0.4+ |
| Embeddings | OpenAI text-embedding-3-small, SentenceTransformers |
| Vector store | ChromaDB |
| Sparse search | BM25 (rank-bm25) |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| PDF parsing | pypdf |
