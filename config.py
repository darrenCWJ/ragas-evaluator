"""Centralized configuration — single source of truth for all tuneable values.

Every constant reads from an environment variable with a sensible default so
the app works out-of-the-box in development but can be reconfigured for
production via ``.env`` or container environment.
"""

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Version — single source of truth is frontend/package.json
# ---------------------------------------------------------------------------
_pkg = Path(__file__).parent / "frontend" / "package.json"
APP_VERSION: str = json.loads(_pkg.read_text(encoding="utf-8")).get("version", "unknown") if _pkg.exists() else "unknown"  # codeql[py/unused-global-variable]

# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # Neon/PostgreSQL connection string; empty = SQLite
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "data/ragas.db"))
CHROMADB_PATH = os.environ.get("CHROMADB_PATH", "data/chromadb")
BM25_PATH = os.environ.get("BM25_PATH", "data/bm25")

# ---------------------------------------------------------------------------
# Default LLM models (used by evaluation, test generation, source verification)
# ---------------------------------------------------------------------------
DEFAULT_EVAL_MODEL = os.environ.get("DEFAULT_EVAL_MODEL", "gpt-4o-mini")
DEFAULT_EVAL_EMBEDDING = os.environ.get("DEFAULT_EVAL_EMBEDDING", "text-embedding-3-small")
DEFAULT_EVAL_MAX_TOKENS = int(os.environ.get("DEFAULT_EVAL_MAX_TOKENS", "16384"))

# ---------------------------------------------------------------------------
# Bot connector default models
# ---------------------------------------------------------------------------
CONNECTOR_DEFAULT_MODELS: dict[str, str] = {  # codeql[py/unused-global-variable]
    "openai": os.environ.get("DEFAULT_OPENAI_MODEL", "gpt-4o-mini"),
    "claude": os.environ.get("DEFAULT_CLAUDE_MODEL", "claude-sonnet-4-20250514"),
    "deepseek": os.environ.get("DEFAULT_DEEPSEEK_MODEL", "deepseek-chat"),
    "gemini": os.environ.get("DEFAULT_GEMINI_MODEL", "gemini-2.0-flash"),
}

# ---------------------------------------------------------------------------
# Connector type registry
# ---------------------------------------------------------------------------
VALID_CONNECTOR_TYPES = {"glean", "openai", "claude", "deepseek", "gemini", "custom", "csv"}

# ---------------------------------------------------------------------------
# Suggestion thresholds
# ---------------------------------------------------------------------------
SUGGESTION_HIGH_THRESHOLD = float(os.environ.get("SUGGESTION_HIGH_THRESHOLD", "0.4"))
SUGGESTION_MEDIUM_THRESHOLD = float(os.environ.get("SUGGESTION_MEDIUM_THRESHOLD", "0.7"))

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
BOT_QUERY_TIMEOUT = float(os.environ.get("BOT_QUERY_TIMEOUT", "120.0"))
METRIC_SCORING_TIMEOUT = float(os.environ.get("METRIC_SCORING_TIMEOUT", "300.0"))
TESTGEN_SUBPROCESS_TIMEOUT = int(os.environ.get("TESTGEN_SUBPROCESS_TIMEOUT", "7200"))
PERSONA_SUBPROCESS_TIMEOUT = int(os.environ.get("PERSONA_SUBPROCESS_TIMEOUT", "3600"))
# KG builds can run for many hours with large overlap_max_nodes (O(n²) cost).
# Default 24 h. Set KG_SUBPROCESS_TIMEOUT=0 in .env to disable the timeout.
_kg_timeout_raw = os.environ.get("KG_SUBPROCESS_TIMEOUT", "86400")
KG_SUBPROCESS_TIMEOUT: "int | None" = None if _kg_timeout_raw == "0" else int(_kg_timeout_raw)  # codeql[py/unused-global-variable]
SOURCE_VERIFY_FETCH_TIMEOUT = int(os.environ.get("SOURCE_VERIFY_FETCH_TIMEOUT", "15"))

# ---------------------------------------------------------------------------
# Upload limits
# ---------------------------------------------------------------------------
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))
MAX_BASELINE_CSV_SIZE = int(os.environ.get("MAX_BASELINE_CSV_SIZE", str(10 * 1024 * 1024)))
MAX_BASELINE_ROWS = int(os.environ.get("MAX_BASELINE_ROWS", "1000"))
MAX_UPLOAD_QA_ROWS = int(os.environ.get("MAX_UPLOAD_QA_ROWS", "2000"))
ALLOWED_FILE_TYPES = {".txt", ".pdf", ".docx"}

# ---------------------------------------------------------------------------
# LLM temperature defaults (not env-configurable — these are tuned values)
# ---------------------------------------------------------------------------
TESTGEN_TOPIC_TEMPERATURE: float = 0.0  # codeql[py/unused-global-variable]
TESTGEN_PERSONA_TEMPERATURE: float = 0.7  # codeql[py/unused-global-variable]
TESTGEN_QUESTION_TEMPERATURE: float = 0.8  # codeql[py/unused-global-variable]

# ---------------------------------------------------------------------------
# Batch sizes
# ---------------------------------------------------------------------------
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "100"))
KG_BATCH_SIZE = int(os.environ.get("KG_BATCH_SIZE", "50"))
PERSONA_MAX_CHARS_PER_BATCH = int(os.environ.get("PERSONA_MAX_CHARS_PER_BATCH", "80000"))

# ---------------------------------------------------------------------------
# Default experiment metrics
# ---------------------------------------------------------------------------
DEFAULT_EXPERIMENT_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "factual_correctness",
    "semantic_similarity",
]

# ---------------------------------------------------------------------------
# Network access
# ---------------------------------------------------------------------------
# Set to true when the app runs on a private network and needs to reach
# internal bots or cite internal document URLs. When false (default),
# private/internal IP ranges are blocked to prevent SSRF on internet-facing deployments.
ALLOW_PRIVATE_ENDPOINTS = os.environ.get("ALLOW_PRIVATE_ENDPOINTS", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Multi-LLM Judge metric
# ---------------------------------------------------------------------------
MULTI_LLM_JUDGE_DEFAULT_EVALUATORS = int(os.environ.get("MULTI_LLM_JUDGE_DEFAULT_EVALUATORS", "3"))
MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD = float(os.environ.get("MULTI_LLM_JUDGE_RELIABILITY_THRESHOLD", "0.6"))
MULTI_LLM_JUDGE_TEMP_MIN = float(os.environ.get("MULTI_LLM_JUDGE_TEMP_MIN", "0.3"))
MULTI_LLM_JUDGE_TEMP_MAX = float(os.environ.get("MULTI_LLM_JUDGE_TEMP_MAX", "0.75"))
_raw_model_assignments = os.environ.get("MULTI_LLM_JUDGE_MODEL_ASSIGNMENTS", "").strip()
MULTI_LLM_JUDGE_MODEL_ASSIGNMENTS: list[str] | None = (  # codeql[py/unused-global-variable]
    [m.strip() for m in _raw_model_assignments.split(",") if m.strip()] or None
)

# ---------------------------------------------------------------------------
# Third-party LLM provider API keys (used by judge multi-model routing)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# ---------------------------------------------------------------------------
# Validation sets (shared across routes and models)
# ---------------------------------------------------------------------------
VALID_CHUNK_METHODS = {"recursive", "parent_child", "semantic", "fixed_overlap", "markdown", "token"}
VALID_EMBEDDING_TYPES = {"dense_openai", "dense_sentence_transformers", "bm25_sparse"}
VALID_SEARCH_TYPES = {"dense", "sparse", "hybrid"}
VALID_RESPONSE_MODES = {"single_shot", "multi_step"}
MAX_CHUNKS_FOR_GENERATION = int(os.environ.get("MAX_CHUNKS_FOR_GENERATION", "0"))

# ---------------------------------------------------------------------------
# RAG context budget
# ---------------------------------------------------------------------------
CONTEXT_CHAR_BUDGET = int(os.environ.get("CONTEXT_CHAR_BUDGET", "100000"))

# ---------------------------------------------------------------------------
# Worker service
# ---------------------------------------------------------------------------
# When set, KG builds are offloaded to dedicated worker service(s).
# Single worker:  KG_WORKER_URL=http://kg-worker:3000
# Multiple workers: KG_WORKER_URLS=http://kg-worker-1:3000,http://kg-worker-2:3000
# (KG_WORKER_URL is kept for backward compatibility)
_kg_worker_raw = os.environ.get("KG_WORKER_URLS") or os.environ.get("KG_WORKER_URL") or ""
KG_WORKER_URLS: list[str] = [u.strip().rstrip("/") for u in _kg_worker_raw.split(",") if u.strip()]  # codeql[py/unused-global-variable]

# Set KG_THREAD_MODE=true to run KG builds in a thread instead of a subprocess.
# Use this in memory-constrained environments to avoid reimporting ragas.
KG_THREAD_MODE: bool = os.environ.get("KG_THREAD_MODE", "").lower() in ("1", "true", "yes")  # codeql[py/unused-global-variable]
