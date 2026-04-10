"""Centralized configuration — single source of truth for all tuneable values.

Every constant reads from an environment variable with a sensible default so
the app works out-of-the-box in development but can be reconfigured for
production via ``.env`` or container environment.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------
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
CONNECTOR_DEFAULT_MODELS: dict[str, str] = {
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
TESTGEN_SUBPROCESS_TIMEOUT = int(os.environ.get("TESTGEN_SUBPROCESS_TIMEOUT", "7200"))
PERSONA_SUBPROCESS_TIMEOUT = int(os.environ.get("PERSONA_SUBPROCESS_TIMEOUT", "3600"))
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
TESTGEN_TOPIC_TEMPERATURE: int | float = 0
TESTGEN_PERSONA_TEMPERATURE: float = 0.7
TESTGEN_QUESTION_TEMPERATURE: float = 0.8

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
# Validation sets (shared across routes and models)
# ---------------------------------------------------------------------------
VALID_CHUNK_METHODS = {"recursive", "parent_child", "semantic", "fixed_overlap", "markdown", "token"}
VALID_EMBEDDING_TYPES = {"dense_openai", "dense_sentence_transformers", "bm25_sparse"}
VALID_SEARCH_TYPES = {"dense", "sparse", "hybrid"}
VALID_RESPONSE_MODES = {"single_shot", "multi_step"}
MAX_CHUNKS_FOR_GENERATION = int(os.environ.get("MAX_CHUNKS_FOR_GENERATION", "0"))
