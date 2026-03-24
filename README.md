# Ragas Evaluator

A comprehensive RAG evaluation tool using [Ragas](https://docs.ragas.io/) metrics. Supports CLI (CSV batch processing), REST API, and a web UI deployable to Vercel.

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
| `factual_correctness` | Factual accuracy (LLM-based) |
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
| `instance_rubrics` | Per-instance custom rubrics |
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
| `tool_call_f1` | Tool call precision/recall |
| `agent_goal_accuracy` | Objective completion |

### SQL Metrics
| Metric | What it measures |
|---|---|
| `datacompy_score` | SQL query result comparison |
| `sql_semantic_equivalence` | Semantic SQL query comparison |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Add your OpenAI API key to .env
```

## Usage

### CLI — CSV Batch Processing

Place your CSV file in `input/` with columns: `Question`, `Answer`, `Retrieve Context` (contexts separated by `||`).

```bash
# Run all metrics
python3 main.py csv sample.csv

# Run specific metrics
python3 main.py csv sample.csv --metrics faithfulness context_recall bleu_score
```

Results are saved to `output/`.

### CLI — REST API

```bash
python3 main.py api --port 8000
```

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Where is the Eiffel Tower?",
    "answer": "The Eiffel Tower is in Paris.",
    "retrieve_context": ["The Eiffel Tower is located in Paris, France."],
    "metrics": ["faithfulness", "answer_relevancy"]
  }'
```

### Web UI (Vercel)

Deploy to Vercel for a browser-based evaluation interface:

```bash
npm i -g vercel
vercel
```

Set `OPENAI_API_KEY` in Vercel project settings under **Settings > Environment Variables**.

## Project Structure

```
├── api/
│   └── evaluate.py          # Vercel serverless function
├── public/
│   └── index.html           # Web UI
├── ragas_test/              # Metric modules (one per metric)
│   ├── faithfulness.py
│   ├── answer_relevancy.py
│   ├── context_precision.py
│   ├── ...
│   └── __init__.py
├── input/                   # CSV input files (gitignored)
├── output/                  # Evaluation results (gitignored)
├── main.py                  # CLI entrypoint
├── requirements.txt
├── vercel.json
└── .env.example
```
