import asyncio
import csv
import io
import json
import logging
import sqlite3
import statistics
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory

from chunking import chunk_text_pipeline
from db.init import get_db as get_db_conn
from rag.query import single_shot_query, multi_step_query
from embedding.engine import embed_texts_dispatch, embed_query_dispatch
from embedding.vectorstore import (
    delete_collection as delete_vector_collection,
    upsert_embeddings,
    search as vector_search,
)

from ragas_test import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    context_entities_recall,
    noise_sensitivity,
    factual_correctness,
    semantic_similarity,
    non_llm_string_similarity,
    bleu_score,
    rouge_score,
    chrf_score,
    exact_match,
    string_presence,
    summarization_score,
    aspect_critic,
    rubrics_score,
    answer_accuracy,
    context_relevance,
    response_groundedness,
)

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

ALL_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "context_entities_recall",
    "noise_sensitivity",
    "factual_correctness",
    "semantic_similarity",
    "non_llm_string_similarity",
    "bleu_score",
    "rouge_score",
    "chrf_score",
    "exact_match",
    "string_presence",
    "summarization_score",
    "aspect_critic",
    "rubrics_score",
    "answer_accuracy",
    "context_relevance",
    "response_groundedness",
]


def setup_scorers(metrics: list[str] = None):
    selected = metrics or ALL_METRICS
    client = AsyncOpenAI()
    llm = llm_factory("gpt-4o-mini", client=client, max_tokens=16384)
    embeddings = embedding_factory("openai", model="text-embedding-3-small", client=client)

    scorers = {}
    for m in selected:
        if m == "faithfulness":
            scorers[m] = faithfulness.create_scorer(llm)
        elif m == "answer_relevancy":
            scorers[m] = answer_relevancy.create_scorer(llm, embeddings)
        elif m == "context_precision":
            scorers[m] = context_precision.create_scorer(llm)
        elif m == "context_recall":
            scorers[m] = context_recall.create_scorer(llm)
        elif m == "context_entities_recall":
            scorers[m] = context_entities_recall.create_scorer(llm)
        elif m == "noise_sensitivity":
            scorers[m] = noise_sensitivity.create_scorer(llm)
        elif m == "factual_correctness":
            scorers[m] = factual_correctness.create_scorer(llm)
        elif m == "semantic_similarity":
            scorers[m] = semantic_similarity.create_scorer(embeddings)
        elif m == "non_llm_string_similarity":
            scorers[m] = non_llm_string_similarity.create_scorer()
        elif m == "bleu_score":
            scorers[m] = bleu_score.create_scorer()
        elif m == "rouge_score":
            scorers[m] = rouge_score.create_scorer()
        elif m == "chrf_score":
            scorers[m] = chrf_score.create_scorer()
        elif m == "exact_match":
            scorers[m] = exact_match.create_scorer()
        elif m == "string_presence":
            scorers[m] = string_presence.create_scorer()
        elif m == "summarization_score":
            scorers[m] = summarization_score.create_scorer(llm)
        elif m == "aspect_critic":
            scorers[m] = aspect_critic.create_scorer(llm)
        elif m == "rubrics_score":
            scorers[m] = rubrics_score.create_scorer(llm)
        elif m == "answer_accuracy":
            scorers[m] = answer_accuracy.create_scorer(llm)
        elif m == "context_relevance":
            scorers[m] = context_relevance.create_scorer(llm)
        elif m == "response_groundedness":
            scorers[m] = response_groundedness.create_scorer(llm)

    return scorers


# --- FastAPI Application (module-level) ---

@asynccontextmanager
async def lifespan(application: FastAPI):
    from db.init import init_db
    try:
        init_db()
        logger.info("Database initialized at data/ragas.db")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)
    yield


app = FastAPI(title="Ragas Evaluator", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---

class TestGenRequest(BaseModel):
    chunks: list[str]
    testset_size: int = 10
    num_personas: int = 3
    custom_personas: list[dict] | None = None
    use_personas: bool = True


class PersonaGenRequest(BaseModel):
    chunks: list[str]
    num_personas: int = 3
    custom_personas: list[dict] | None = None


VALID_QUESTION_STATUSES = {"pending", "approved", "rejected", "edited"}
VALID_ANNOTATION_STATUSES = {"approved", "rejected", "edited"}
VALID_BULK_ACTIONS = {"approve", "reject", "approve_all", "reject_all"}
BULK_ACTION_TO_STATUS = {"approve": "approved", "reject": "rejected", "approve_all": "approved", "reject_all": "rejected"}

MAX_CHUNKS_FOR_GENERATION = 500


class TestSetCreate(BaseModel):
    chunk_config_id: int
    name: str | None = None
    testset_size: int = 10
    num_personas: int = 3
    custom_personas: list[dict] | None = None
    use_personas: bool = True

    @field_validator("testset_size")
    @classmethod
    def validate_testset_size(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("testset_size must be between 1 and 100")
        return v

    @field_validator("num_personas")
    @classmethod
    def validate_num_personas(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("num_personas must be between 1 and 10")
        return v


class QuestionAnnotation(BaseModel):
    status: str
    user_edited_answer: str | None = None
    user_notes: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_ANNOTATION_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {', '.join(sorted(VALID_ANNOTATION_STATUSES))}")
        return v


class BulkAnnotation(BaseModel):
    action: str
    question_ids: list[int] | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in VALID_BULK_ACTIONS:
            raise ValueError(f"Invalid action '{v}'. Must be one of: {', '.join(sorted(VALID_BULK_ACTIONS))}")
        return v


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Project name must not be blank")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Project name must not be blank")
        return v


class ApiConfigCreate(BaseModel):
    endpoint_url: str
    api_key: str | None = None
    headers_json: str | None = None

    @field_validator("endpoint_url")
    @classmethod
    def url_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Endpoint URL must not be blank")
        return v


VALID_CHUNK_METHODS = {"recursive", "parent_child", "semantic", "fixed_overlap"}


class ChunkConfigCreate(BaseModel):
    name: str
    method: str
    params: dict
    step2_method: str | None = None
    step2_params: dict | None = None

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_CHUNK_METHODS:
            raise ValueError(f"method must be one of: {', '.join(sorted(VALID_CHUNK_METHODS))}")
        return v

    @field_validator("step2_method")
    @classmethod
    def validate_step2_method(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CHUNK_METHODS:
            raise ValueError(f"step2_method must be one of: {', '.join(sorted(VALID_CHUNK_METHODS))}")
        return v

    def model_post_init(self, __context) -> None:
        if (self.step2_method is None) != (self.step2_params is None):
            raise ValueError("step2_method and step2_params must both be set or both be None")


VALID_EMBEDDING_TYPES = {"dense_openai", "dense_sentence_transformers", "bm25_sparse"}


class EmbeddingConfigCreate(BaseModel):
    name: str
    type: str
    model_name: str
    params: dict = {}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_EMBEDDING_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(VALID_EMBEDDING_TYPES))}")
        return v


class EmbedRequest(BaseModel):
    chunk_config_id: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class HybridSearchRequest(BaseModel):
    query: str
    dense_config_id: int
    sparse_config_id: int
    top_k: int = 5
    alpha: float = 0.5

    @field_validator("alpha")
    @classmethod
    def validate_alpha(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("alpha must be between 0.0 and 1.0")
        return v


VALID_SEARCH_TYPES = {"dense", "sparse", "hybrid"}
VALID_RESPONSE_MODES = {"single_shot", "multi_step"}
ALLOWED_LLM_PARAMS = {"temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"}


class RagConfigCreate(BaseModel):
    name: str
    embedding_config_id: int
    chunk_config_id: int
    search_type: str
    llm_model: str
    top_k: int = 5
    system_prompt: str | None = None
    llm_params: dict | None = None
    sparse_config_id: int | None = None
    alpha: float | None = None
    response_mode: str = "single_shot"
    max_steps: int = 3

    @field_validator("search_type")
    @classmethod
    def validate_search_type(cls, v: str) -> str:
        if v not in VALID_SEARCH_TYPES:
            raise ValueError(f"search_type must be one of: {', '.join(sorted(VALID_SEARCH_TYPES))}")
        return v

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, v: str) -> str:
        if v not in VALID_RESPONSE_MODES:
            raise ValueError(f"response_mode must be one of: {', '.join(sorted(VALID_RESPONSE_MODES))}")
        return v

    @field_validator("max_steps")
    @classmethod
    def validate_max_steps(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("max_steps must be between 1 and 10")
        return v

    @field_validator("llm_params")
    @classmethod
    def validate_llm_params(cls, v: dict | None) -> dict | None:
        if v is not None:
            unknown = set(v.keys()) - ALLOWED_LLM_PARAMS
            if unknown:
                raise ValueError(f"Unknown llm_params keys: {', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(ALLOWED_LLM_PARAMS))}")
        return v

    def model_post_init(self, __context) -> None:
        if self.search_type == "hybrid":
            if self.sparse_config_id is None:
                raise ValueError("sparse_config_id is required when search_type is 'hybrid'")
            if self.alpha is None:
                raise ValueError("alpha is required when search_type is 'hybrid'")
            if self.alpha < 0.0 or self.alpha > 1.0:
                raise ValueError("alpha must be between 0.0 and 1.0")


class RagConfigUpdate(BaseModel):
    name: str | None = None
    embedding_config_id: int | None = None
    chunk_config_id: int | None = None
    search_type: str | None = None
    llm_model: str | None = None
    top_k: int | None = None
    system_prompt: str | None = None
    llm_params: dict | None = None
    sparse_config_id: int | None = None
    alpha: float | None = None
    response_mode: str | None = None
    max_steps: int | None = None

    @field_validator("search_type")
    @classmethod
    def validate_search_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_SEARCH_TYPES:
            raise ValueError(f"search_type must be one of: {', '.join(sorted(VALID_SEARCH_TYPES))}")
        return v

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_RESPONSE_MODES:
            raise ValueError(f"response_mode must be one of: {', '.join(sorted(VALID_RESPONSE_MODES))}")
        return v

    @field_validator("max_steps")
    @classmethod
    def validate_max_steps(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 10):
            raise ValueError("max_steps must be between 1 and 10")
        return v

    @field_validator("llm_params")
    @classmethod
    def validate_llm_params(cls, v: dict | None) -> dict | None:
        if v is not None:
            unknown = set(v.keys()) - ALLOWED_LLM_PARAMS
            if unknown:
                raise ValueError(f"Unknown llm_params keys: {', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(ALLOWED_LLM_PARAMS))}")
        return v


class RagQueryRequest(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        if len(v) > 10000:
            raise ValueError("query must not exceed 10000 characters")
        return v


VALID_EXPERIMENT_STATUSES = {"pending", "running", "completed", "failed"}

DEFAULT_EXPERIMENT_METRICS = [
    "faithfulness", "answer_relevancy", "context_precision",
    "context_recall", "factual_correctness", "semantic_similarity",
]


class ExperimentCreate(BaseModel):
    test_set_id: int
    rag_config_id: int
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 200:
            raise ValueError("name must not exceed 200 characters")
        return v


class ExperimentRunRequest(BaseModel):
    metrics: list[str] | None = None


class SuggestionUpdate(BaseModel):
    implemented: bool


class ApplySuggestionRequest(BaseModel):
    override_value: str | None = None
    experiment_name: str | None = None

    @field_validator("experiment_name")
    @classmethod
    def validate_experiment_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("experiment_name must not be empty")
            if len(v) > 200:
                raise ValueError("experiment_name must not exceed 200 characters")
        return v


def _build_virtual_rag_config_row(experiment_row, project_id: int) -> dict:
    """Build a dict satisfying the rag_config_row interface for RAG query functions."""
    retrieval_config = json.loads(experiment_row["retrieval_config_json"]) if experiment_row["retrieval_config_json"] else {}
    return {
        "project_id": project_id,
        "llm_model": experiment_row["model"],
        "llm_params_json": experiment_row["model_params_json"],
        "chunk_config_id": experiment_row["chunk_config_id"],
        "embedding_config_id": experiment_row["embedding_config_id"],
        "search_type": retrieval_config.get("search_type", "dense"),
        "sparse_config_id": retrieval_config.get("sparse_config_id"),
        "alpha": retrieval_config.get("alpha"),
        "top_k": retrieval_config.get("top_k", 5),
        "system_prompt": retrieval_config.get("system_prompt"),
        "response_mode": retrieval_config.get("response_mode", "single_shot"),
        "max_steps": retrieval_config.get("max_steps", 3),
    }


async def _evaluate_experiment_row(
    scorers: dict,
    question: str,
    generated_answer: str,
    reference_answer: str,
    contexts: list[str],
) -> dict:
    """Evaluate a generated answer against reference using selected metrics.

    Properly separates generated_answer from reference_answer for metrics that compare the two.
    """
    results = {}

    for name, scorer in scorers.items():
        try:
            if name == "faithfulness":
                results[name] = await faithfulness.score(scorer, question, generated_answer, contexts)
            elif name == "answer_relevancy":
                results[name] = await answer_relevancy.score(scorer, question, generated_answer)
            elif name == "context_precision":
                results[name] = await context_precision.score(scorer, question, generated_answer, contexts)
            elif name == "context_recall":
                results[name] = await context_recall.score(scorer, question, generated_answer, contexts)
            elif name == "context_entities_recall":
                results[name] = await context_entities_recall.score(scorer, generated_answer, contexts)
            elif name == "noise_sensitivity":
                results[name] = await noise_sensitivity.score(scorer, question, generated_answer, reference_answer, contexts)
            elif name == "factual_correctness":
                results[name] = await factual_correctness.score(scorer, generated_answer, reference_answer)
            elif name == "semantic_similarity":
                results[name] = await semantic_similarity.score(scorer, generated_answer, reference_answer)
            elif name == "non_llm_string_similarity":
                results[name] = await non_llm_string_similarity.score(scorer, generated_answer, reference_answer)
            elif name == "bleu_score":
                results[name] = await bleu_score.score(scorer, generated_answer, reference_answer)
            elif name == "rouge_score":
                results[name] = await rouge_score.score(scorer, generated_answer, reference_answer)
            elif name == "chrf_score":
                results[name] = await chrf_score.score(scorer, generated_answer, reference_answer)
            elif name == "exact_match":
                results[name] = await exact_match.score(scorer, generated_answer, reference_answer)
            elif name == "string_presence":
                results[name] = await string_presence.score(scorer, generated_answer, reference_answer)
            elif name == "summarization_score":
                results[name] = await summarization_score.score(scorer, generated_answer, contexts)
            elif name == "aspect_critic":
                results[name] = await aspect_critic.score(scorer, question, generated_answer, contexts)
            elif name == "rubrics_score":
                results[name] = await rubrics_score.score(scorer, question, generated_answer, contexts)
            elif name == "answer_accuracy":
                results[name] = await answer_accuracy.score(scorer, question, generated_answer, reference_answer)
            elif name == "context_relevance":
                results[name] = await context_relevance.score(scorer, question, contexts)
            elif name == "response_groundedness":
                results[name] = await response_groundedness.score(scorer, generated_answer, contexts)
        except Exception as e:
            logger.warning("Metric %s failed: %s", name, e)
            results[name] = None

    return results


# --- API Routes ---

@app.get("/api/health")
async def health_check():
    try:
        from db.init import get_db
        conn = get_db()
        conn.execute("SELECT 1")
        return {"status": "ok", "version": "0.1.0", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "version": "0.1.0", "database": "disconnected"},
        )


@app.post("/api/generate-testset")
async def generate_testset(req: TestGenRequest):
    from ragas_test.testgen import (
        generate_testset_from_chunks,
        generate_testset_with_personas,
    )

    if req.use_personas:
        result = await generate_testset_with_personas(
            chunks=req.chunks,
            testset_size=req.testset_size,
            num_personas=req.num_personas,
            custom_personas=req.custom_personas,
        )
        return result
    else:
        questions = await generate_testset_from_chunks(
            chunks=req.chunks,
            testset_size=req.testset_size,
            custom_personas=req.custom_personas,
        )
        return {"personas": [], "questions": questions}


@app.post("/api/generate-personas")
async def gen_personas(req: PersonaGenRequest):
    from ragas_test.testgen import generate_personas

    personas = generate_personas(
        chunks=req.chunks,
        num_personas=req.num_personas,
        custom_personas=req.custom_personas,
    )
    return {
        "personas": [
            {"name": p.name, "role_description": p.role_description}
            for p in personas
        ]
    }


@app.post("/api/upload-document")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return {
        "filename": file.filename,
        "chunks": paragraphs,
        "num_chunks": len(paragraphs),
    }


# --- Project CRUD Routes ---

@app.post("/api/projects", status_code=201)
async def create_project(req: ProjectCreate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (req.name, req.description),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Project name already exists")


@app.get("/api/projects")
async def list_projects():
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, description, created_at, updated_at FROM projects"
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return dict(row)


@app.put("/api/projects/{project_id}")
async def update_project(project_id: int, req: ProjectUpdate):
    if req.name is None and req.description is None:
        raise HTTPException(status_code=400, detail="No fields to update")
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = []
    params = []
    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name)
    if req.description is not None:
        updates.append("description = ?")
        params.append(req.description)
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(project_id)
    try:
        conn.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Project name already exists")
    row = conn.execute(
        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    return dict(row)


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    conn = get_db_conn()
    existing = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return {"detail": "Project deleted"}


# --- External Baselines Routes ---

MAX_BASELINE_CSV_SIZE = 10 * 1024 * 1024  # 10MB
MAX_BASELINE_ROWS = 1000


def _sanitize_csv_value(val: str) -> str:
    """Strip whitespace and prevent CSV injection."""
    val = val.strip()
    if val and val[0] in ("=", "+", "-", "@"):
        val = "'" + val
    return val


@app.post("/api/projects/{project_id}/baselines/upload-csv", status_code=201)
async def upload_baseline_csv(project_id: int, file: UploadFile = File(...)):
    conn = get_db_conn()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    if len(content) > MAX_BASELINE_CSV_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum 10MB.")

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode file as UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no headers")

    lower_fields = [f.strip().lower() for f in reader.fieldnames]
    if "question" not in lower_fields or "answer" not in lower_fields:
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have 'question' and 'answer' columns. Found: {', '.join(reader.fieldnames)}",
        )

    # Build column name mapping (case-insensitive)
    col_map = {}
    for orig, low in zip(reader.fieldnames, lower_fields):
        if low == "question":
            col_map["question"] = orig
        elif low == "answer":
            col_map["answer"] = orig
        elif low in ("sources", "source", "context", "contexts"):
            col_map["sources"] = orig

    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_BASELINE_ROWS:
            break
        q = _sanitize_csv_value(row.get(col_map["question"], ""))
        a = _sanitize_csv_value(row.get(col_map["answer"], ""))
        if not q or not a:
            continue
        s = _sanitize_csv_value(row.get(col_map.get("sources", ""), "") or "")
        rows.append((project_id, q, a, s, "csv"))

    if not rows:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    conn.executemany(
        "INSERT INTO external_baselines (project_id, question, answer, sources, source_type) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    return {
        "imported": len(rows),
        "preview": [
            {"question": r[1], "answer": r[2], "sources": r[3]}
            for r in rows[:5]
        ],
    }


@app.get("/api/projects/{project_id}/baselines")
async def list_baselines(project_id: int):
    conn = get_db_conn()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT id, project_id, question, answer, sources, source_type, created_at FROM external_baselines WHERE project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()

    return [
        {
            "id": r[0], "project_id": r[1], "question": r[2], "answer": r[3],
            "sources": r[4], "source_type": r[5], "created_at": r[6],
        }
        for r in rows
    ]


@app.delete("/api/projects/{project_id}/baselines/{baseline_id}")
async def delete_baseline(project_id: int, baseline_id: int):
    conn = get_db_conn()
    existing = conn.execute(
        "SELECT id FROM external_baselines WHERE id = ? AND project_id = ?",
        (baseline_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
    conn.execute("DELETE FROM external_baselines WHERE id = ?", (baseline_id,))
    conn.commit()
    return {"detail": "Baseline deleted"}


@app.delete("/api/projects/{project_id}/baselines")
async def clear_baselines(project_id: int):
    conn = get_db_conn()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conn.execute("DELETE FROM external_baselines WHERE project_id = ?", (project_id,))
    conn.commit()
    return {"detail": "All baselines cleared"}


# --- API Config Routes ---


@app.post("/api/projects/{project_id}/api-config", status_code=201)
async def save_api_config(project_id: int, payload: ApiConfigCreate):
    conn = get_db_conn()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = conn.execute("SELECT id FROM api_configs WHERE project_id = ?", (project_id,)).fetchone()

    if existing:
        conn.execute(
            "UPDATE api_configs SET endpoint_url = ?, api_key = ?, headers_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
            (payload.endpoint_url, payload.api_key, payload.headers_json, project_id),
        )
        config_id = existing[0]
    else:
        cur = conn.execute(
            "INSERT INTO api_configs (project_id, endpoint_url, api_key, headers_json) VALUES (?, ?, ?, ?)",
            (project_id, payload.endpoint_url, payload.api_key, payload.headers_json),
        )
        config_id = cur.lastrowid

    conn.commit()

    row = conn.execute(
        "SELECT id, project_id, endpoint_url, api_key, headers_json, created_at, updated_at FROM api_configs WHERE id = ?",
        (config_id,),
    ).fetchone()

    return {
        "id": row[0], "project_id": row[1], "endpoint_url": row[2],
        "api_key": row[3], "headers_json": row[4],
        "created_at": row[5], "updated_at": row[6],
    }


@app.get("/api/projects/{project_id}/api-config")
async def get_api_config(project_id: int):
    conn = get_db_conn()
    row = conn.execute(
        "SELECT id, project_id, endpoint_url, api_key, headers_json, created_at, updated_at FROM api_configs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No API config found for this project")
    return {
        "id": row[0], "project_id": row[1], "endpoint_url": row[2],
        "api_key": row[3], "headers_json": row[4],
        "created_at": row[5], "updated_at": row[6],
    }


@app.delete("/api/projects/{project_id}/api-config")
async def delete_api_config(project_id: int):
    conn = get_db_conn()
    existing = conn.execute("SELECT id FROM api_configs WHERE project_id = ?", (project_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="No API config found for this project")
    conn.execute("DELETE FROM api_configs WHERE project_id = ?", (project_id,))
    conn.commit()
    return {"detail": "API config deleted"}


# --- Document Routes ---

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_FILE_TYPES = {".txt", ".pdf"}


@app.post("/api/projects/{project_id}/documents", status_code=201)
async def upload_project_document(project_id: int, file: UploadFile = File(...)):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_FILE_TYPES))}",
        )

    content_bytes = await file.read()
    if len(content_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 50MB size limit")

    if ext == ".txt":
        text = content_bytes.decode("utf-8", errors="ignore")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")

    cursor = conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content) VALUES (?, ?, ?, ?)",
        (project_id, filename, ext, text),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, filename, file_type, created_at FROM documents WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


@app.get("/api/projects/{project_id}/documents")
async def list_project_documents(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute(
        "SELECT id, filename, file_type, created_at FROM documents WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/projects/{project_id}/documents/{document_id}")
async def get_project_document(project_id: int, document_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, project_id, filename, file_type, content, created_at FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@app.delete("/api/projects/{project_id}/documents/{document_id}")
async def delete_project_document(project_id: int, document_id: int):
    conn = get_db_conn()
    existing = conn.execute(
        "SELECT id FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Document not found")
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()
    return {"detail": "Document deleted"}


# --- Chunk Config Routes ---

def _parse_chunk_config_row(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json"))
    s2m = d.pop("step2_method", None)
    s2p = d.pop("step2_params_json", None)
    d["step2_method"] = s2m
    d["step2_params"] = json.loads(s2p) if s2p else None
    return d


@app.post("/api/projects/{project_id}/chunk-configs", status_code=201)
async def create_chunk_config(project_id: int, req: ChunkConfigCreate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    cursor = conn.execute(
        "INSERT INTO chunk_configs (project_id, name, method, params_json, step2_method, step2_params_json) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, req.name, req.method, json.dumps(req.params),
         req.step2_method, json.dumps(req.step2_params) if req.step2_params else None),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM chunk_configs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _parse_chunk_config_row(row)


@app.get("/api/projects/{project_id}/chunk-configs")
async def list_chunk_configs(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute("SELECT * FROM chunk_configs WHERE project_id = ?", (project_id,)).fetchall()
    return [_parse_chunk_config_row(r) for r in rows]


@app.get("/api/projects/{project_id}/chunk-configs/{config_id}")
async def get_chunk_config(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")
    return _parse_chunk_config_row(row)


@app.delete("/api/projects/{project_id}/chunk-configs/{config_id}")
async def delete_chunk_config(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")
    # Referential integrity: check if any RAG configs reference this chunk config
    rag_refs = conn.execute(
        "SELECT COUNT(*) as cnt FROM rag_configs WHERE chunk_config_id = ?",
        (config_id,),
    ).fetchone()
    if rag_refs["cnt"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Chunk config is referenced by {rag_refs['cnt']} RAG config(s)",
        )
    conn.execute("DELETE FROM chunk_configs WHERE id = ?", (config_id,))
    conn.commit()
    return {"detail": "Chunk config deleted"}


@app.post("/api/projects/{project_id}/chunk-configs/{config_id}/generate")
async def generate_chunks(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    config_row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    method = config_row["method"]
    params = json.loads(config_row["params_json"])
    step2_method = config_row["step2_method"]
    step2_params = json.loads(config_row["step2_params_json"]) if config_row["step2_params_json"] else None

    # Delete existing chunks for this config (re-generation replaces prior)
    conn.execute("DELETE FROM chunks WHERE chunk_config_id = ?", (config_id,))

    documents = conn.execute(
        "SELECT id, filename, content FROM documents WHERE project_id = ?",
        (project_id,),
    ).fetchall()

    total_chunks = 0
    doc_results = []
    for doc in documents:
        chunks = chunk_text_pipeline(doc["content"], method, params, step2_method, step2_params)
        for chunk in chunks:
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_config_id, content) VALUES (?, ?, ?)",
                (doc["id"], config_id, chunk),
            )
        total_chunks += len(chunks)
        doc_results.append({"document_id": doc["id"], "filename": doc["filename"], "chunk_count": len(chunks)})

    conn.commit()
    return {"total_chunks": total_chunks, "documents": doc_results}


@app.post("/api/projects/{project_id}/chunk-configs/{config_id}/preview")
async def preview_chunks(project_id: int, config_id: int, document_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    config_row = conn.execute(
        "SELECT * FROM chunk_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")
    doc = conn.execute(
        "SELECT id, filename, content FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    method = config_row["method"]
    params = json.loads(config_row["params_json"])
    step2_method = config_row["step2_method"]
    step2_params = json.loads(config_row["step2_params_json"]) if config_row["step2_params_json"] else None

    chunks = chunk_text_pipeline(doc["content"], method, params, step2_method, step2_params)
    return {"document_id": doc["id"], "filename": doc["filename"], "chunks": chunks, "chunk_count": len(chunks)}


# --- Embedding Config Routes ---

def _parse_embedding_config_row(row) -> dict:
    d = dict(row)
    pj = d.pop("params_json", None)
    d["params"] = json.loads(pj) if pj else {}
    return d


@app.post("/api/projects/{project_id}/embedding-configs", status_code=201)
async def create_embedding_config(project_id: int, req: EmbeddingConfigCreate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    cursor = conn.execute(
        "INSERT INTO embedding_configs (project_id, name, type, model_name, params_json) VALUES (?, ?, ?, ?, ?)",
        (project_id, req.name, req.type, req.model_name, json.dumps(req.params)),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM embedding_configs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _parse_embedding_config_row(row)


@app.get("/api/projects/{project_id}/embedding-configs")
async def list_embedding_configs(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute("SELECT * FROM embedding_configs WHERE project_id = ?", (project_id,)).fetchall()
    return [_parse_embedding_config_row(r) for r in rows]


@app.get("/api/projects/{project_id}/embedding-configs/{config_id}")
async def get_embedding_config(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")
    return _parse_embedding_config_row(row)


@app.delete("/api/projects/{project_id}/embedding-configs/{config_id}")
async def delete_embedding_config(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    config_row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")
    # Referential integrity: check if any RAG configs reference this embedding config
    rag_refs = conn.execute(
        "SELECT COUNT(*) as cnt FROM rag_configs WHERE embedding_config_id = ? OR sparse_config_id = ?",
        (config_id, config_id),
    ).fetchone()
    if rag_refs["cnt"] > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Embedding config is referenced by {rag_refs['cnt']} RAG config(s)",
        )
    # Cascade: clean up stored data based on type
    if config_row["type"] == "bm25_sparse":
        from embedding.bm25 import delete_index, get_index_path
        delete_index(get_index_path(project_id, config_id))
    else:
        collection_name = f"project_{project_id}_embed_{config_id}"
        delete_vector_collection(collection_name)
    conn.execute("DELETE FROM embedding_configs WHERE id = ?", (config_id,))
    conn.commit()
    return {"detail": "Embedding config deleted"}


@app.post("/api/projects/{project_id}/embedding-configs/{config_id}/embed")
async def embed_chunks(project_id: int, config_id: int, req: EmbedRequest):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate embedding config belongs to project
    config_row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")

    # Validate chunk config belongs to project
    chunk_config = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if chunk_config is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    # Fetch all chunks for this chunk config
    chunks = conn.execute(
        "SELECT id, document_id, content FROM chunks WHERE chunk_config_id = ?",
        (req.chunk_config_id,),
    ).fetchall()

    # Empty state: 0 chunks → return early
    if not chunks:
        return {"total_embedded": 0, "collection": f"project_{project_id}_embed_{config_id}"}

    embedding_type = config_row["type"]
    model_name = config_row["model_name"]
    params = json.loads(config_row["params_json"]) if config_row["params_json"] else {}

    texts = [chunk["content"] for chunk in chunks]
    metadatas = [{"document_id": chunk["document_id"], "chunk_id": chunk["id"]} for chunk in chunks]

    if embedding_type == "bm25_sparse":
        # BM25: build index and save to disk (not ChromaDB)
        from embedding.bm25 import build_and_save_index, get_index_path
        index_path = get_index_path(project_id, config_id)
        try:
            build_and_save_index(texts, metadatas, index_path)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"BM25 index build failed: {e}")
        return {"total_embedded": len(chunks), "index": index_path}
    else:
        # Dense embedding: compute-then-swap into ChromaDB
        try:
            embeddings = await embed_texts_dispatch(texts, embedding_type, model_name, params)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Embedding API failed: {e}")

        collection_name = f"project_{project_id}_embed_{config_id}"
        delete_vector_collection(collection_name)

        ids = [f"chunk_{chunk['id']}" for chunk in chunks]
        documents = texts

        upsert_embeddings(collection_name, ids, embeddings, documents, metadatas)

        return {"total_embedded": len(chunks), "collection": collection_name}


@app.post("/api/projects/{project_id}/embedding-configs/{config_id}/search")
async def search_embeddings(project_id: int, config_id: int, req: SearchRequest):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate embedding config belongs to project
    config_row = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if config_row is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")

    embedding_type = config_row["type"]
    model_name = config_row["model_name"]
    params = json.loads(config_row["params_json"]) if config_row["params_json"] else {}

    if embedding_type == "bm25_sparse":
        # BM25: load index and search
        from embedding.bm25 import load_index, search_bm25, get_index_path
        index_path = get_index_path(project_id, config_id)
        try:
            index, texts, metadatas = load_index(index_path)
        except FileNotFoundError:
            return {"results": [], "query": req.query, "top_k": req.top_k}
        results = search_bm25(index, texts, metadatas, req.query, req.top_k)
        return {"results": results, "query": req.query, "top_k": req.top_k}
    else:
        # Dense: embed query and search ChromaDB
        try:
            query_embedding = await embed_query_dispatch(req.query, embedding_type, model_name, params)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Embedding API failed: {e}")

        collection_name = f"project_{project_id}_embed_{config_id}"
        results = vector_search(collection_name, query_embedding, req.top_k)

        output = []
        for r in results:
            output.append({
                "content": r["content"],
                "document_id": r["metadata"].get("document_id"),
                "chunk_id": r["metadata"].get("chunk_id"),
                "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else None,
                "distance": r["distance"],
            })

        return {"results": output, "query": req.query, "top_k": req.top_k}


# --- RAG Config Routes ---

def _parse_rag_config_row(row) -> dict:
    d = dict(row)
    lpj = d.pop("llm_params_json", None)
    d["llm_params"] = json.loads(lpj) if lpj else None
    return d


@app.post("/api/projects/{project_id}/rag-configs", status_code=201)
async def create_rag_config(project_id: int, req: RagConfigCreate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate embedding_config_id belongs to project
    ec = conn.execute(
        "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
        (req.embedding_config_id, project_id),
    ).fetchone()
    if ec is None:
        raise HTTPException(status_code=404, detail="Embedding config not found")

    # Validate chunk_config_id belongs to project
    cc = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if cc is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    # Validate sparse_config_id belongs to project (if hybrid)
    if req.search_type == "hybrid" and req.sparse_config_id is not None:
        sc = conn.execute(
            "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
            (req.sparse_config_id, project_id),
        ).fetchone()
        if sc is None:
            raise HTTPException(status_code=404, detail="Sparse embedding config not found")

    cursor = conn.execute(
        """INSERT INTO rag_configs
           (project_id, name, embedding_config_id, chunk_config_id, search_type,
            sparse_config_id, alpha, llm_model, llm_params_json, top_k, system_prompt,
            response_mode, max_steps)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, req.name, req.embedding_config_id, req.chunk_config_id, req.search_type,
         req.sparse_config_id, req.alpha, req.llm_model,
         json.dumps(req.llm_params) if req.llm_params else None,
         req.top_k, req.system_prompt, req.response_mode, req.max_steps),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM rag_configs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _parse_rag_config_row(row)


@app.get("/api/projects/{project_id}/rag-configs")
async def list_rag_configs(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute("SELECT * FROM rag_configs WHERE project_id = ?", (project_id,)).fetchall()
    return [_parse_rag_config_row(r) for r in rows]


def _expand_rag_config(rag_row, conn) -> dict:
    """Add linked chunk_config and embedding_config details to a parsed rag config dict."""
    d = _parse_rag_config_row(rag_row)
    cc = conn.execute(
        "SELECT name, method, params_json FROM chunk_configs WHERE id = ?",
        (rag_row["chunk_config_id"],),
    ).fetchone()
    if cc:
        d["chunk_config"] = {"name": cc["name"], "method": cc["method"], "params": json.loads(cc["params_json"])}
    else:
        d["chunk_config"] = None
    ec = conn.execute(
        "SELECT name, type, model_name FROM embedding_configs WHERE id = ?",
        (rag_row["embedding_config_id"],),
    ).fetchone()
    if ec:
        d["embedding_config"] = {"name": ec["name"], "type": ec["type"], "model_name": ec["model_name"]}
    else:
        d["embedding_config"] = None
    return d


@app.get("/api/projects/{project_id}/rag-configs/expanded")
async def list_rag_configs_expanded(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute("SELECT * FROM rag_configs WHERE project_id = ?", (project_id,)).fetchall()
    return [_expand_rag_config(r, conn) for r in rows]


@app.get("/api/projects/{project_id}/rag-configs/{config_id}/expanded")
async def get_rag_config_expanded(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="RAG config not found")
    return _expand_rag_config(row, conn)


@app.get("/api/projects/{project_id}/rag-configs/{config_id}")
async def get_rag_config(project_id: int, config_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="RAG config not found")
    return _parse_rag_config_row(row)


@app.put("/api/projects/{project_id}/rag-configs/{config_id}")
async def update_rag_config(project_id: int, config_id: int, req: RagConfigUpdate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="RAG config not found")

    # Project-scoped FK validation for changed reference fields
    if req.embedding_config_id is not None:
        ec = conn.execute(
            "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
            (req.embedding_config_id, project_id),
        ).fetchone()
        if ec is None:
            raise HTTPException(status_code=404, detail="Embedding config not found")

    if req.chunk_config_id is not None:
        cc = conn.execute(
            "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
            (req.chunk_config_id, project_id),
        ).fetchone()
        if cc is None:
            raise HTTPException(status_code=404, detail="Chunk config not found")

    if req.sparse_config_id is not None:
        sc = conn.execute(
            "SELECT id FROM embedding_configs WHERE id = ? AND project_id = ?",
            (req.sparse_config_id, project_id),
        ).fetchone()
        if sc is None:
            raise HTTPException(status_code=404, detail="Sparse embedding config not found")

    # Determine effective search_type for hybrid validation
    effective_search_type = req.search_type if req.search_type is not None else existing["search_type"]
    if effective_search_type == "hybrid":
        effective_sparse = req.sparse_config_id if req.sparse_config_id is not None else existing["sparse_config_id"]
        effective_alpha = req.alpha if req.alpha is not None else existing["alpha"]
        if effective_sparse is None:
            raise HTTPException(status_code=422, detail="sparse_config_id is required when search_type is 'hybrid'")
        if effective_alpha is None:
            raise HTTPException(status_code=422, detail="alpha is required when search_type is 'hybrid'")
        if effective_alpha < 0.0 or effective_alpha > 1.0:
            raise HTTPException(status_code=422, detail="alpha must be between 0.0 and 1.0")

    updates = []
    params = []
    field_map = {
        "name": req.name,
        "embedding_config_id": req.embedding_config_id,
        "chunk_config_id": req.chunk_config_id,
        "search_type": req.search_type,
        "llm_model": req.llm_model,
        "top_k": req.top_k,
        "system_prompt": req.system_prompt,
        "sparse_config_id": req.sparse_config_id,
        "alpha": req.alpha,
        "response_mode": req.response_mode,
        "max_steps": req.max_steps,
    }
    for col, val in field_map.items():
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)
    if req.llm_params is not None:
        updates.append("llm_params_json = ?")
        params.append(json.dumps(req.llm_params))

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(config_id)
    conn.execute(f"UPDATE rag_configs SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM rag_configs WHERE id = ?", (config_id,)).fetchone()
    return _parse_rag_config_row(row)


@app.delete("/api/projects/{project_id}/rag-configs/{config_id}")
async def delete_rag_config(project_id: int, config_id: int):
    conn = get_db_conn()
    existing = conn.execute(
        "SELECT id FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="RAG config not found")
    conn.execute("DELETE FROM rag_configs WHERE id = ?", (config_id,))
    conn.commit()
    return {"detail": "RAG config deleted"}


# --- RAG Query Route ---

@app.post("/api/projects/{project_id}/rag-configs/{config_id}/query")
async def rag_query(project_id: int, config_id: int, req: RagQueryRequest):
    from rag.query import single_shot_query, multi_step_query

    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rag_config = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (config_id, project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(status_code=404, detail="RAG config not found")

    response_mode = rag_config["response_mode"]
    if response_mode == "multi_step":
        result = await multi_step_query(req.query, rag_config, conn)
    else:
        result = await single_shot_query(req.query, rag_config, conn)
    return result


# --- Hybrid Search Route ---

@app.post("/api/projects/{project_id}/hybrid-search")
async def hybrid_search(project_id: int, req: HybridSearchRequest):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate dense config
    dense_config = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (req.dense_config_id, project_id),
    ).fetchone()
    if dense_config is None:
        raise HTTPException(status_code=404, detail="Dense embedding config not found")

    # Validate sparse config
    sparse_config = conn.execute(
        "SELECT * FROM embedding_configs WHERE id = ? AND project_id = ?",
        (req.sparse_config_id, project_id),
    ).fetchone()
    if sparse_config is None:
        raise HTTPException(status_code=404, detail="Sparse embedding config not found")

    # --- Dense search ---
    dense_results = []
    dense_type = dense_config["type"]
    dense_model = dense_config["model_name"]
    dense_params = json.loads(dense_config["params_json"]) if dense_config["params_json"] else {}

    try:
        query_embedding = await embed_query_dispatch(req.query, dense_type, dense_model, dense_params)
        collection_name = f"project_{project_id}_embed_{req.dense_config_id}"
        raw_dense = vector_search(collection_name, query_embedding, req.top_k)
        for r in raw_dense:
            dense_results.append({
                "content": r["content"],
                "chunk_id": r["metadata"].get("chunk_id"),
                "document_id": r["metadata"].get("document_id"),
                "score": 1.0 / (1.0 + r["distance"]) if r["distance"] is not None else 0.0,
            })
    except Exception:
        # Dense search failed or collection missing — proceed with sparse only
        pass

    # --- Sparse (BM25) search ---
    sparse_results = []
    from embedding.bm25 import load_index, search_bm25, get_index_path
    index_path = get_index_path(project_id, req.sparse_config_id)
    try:
        index, texts, metadatas = load_index(index_path)
        sparse_results = search_bm25(index, texts, metadatas, req.query, req.top_k)
    except FileNotFoundError:
        pass

    # --- Reciprocal Rank Fusion ---
    RRF_K = 60
    chunk_scores: dict[int, dict] = {}

    for rank, r in enumerate(dense_results):
        cid = r["chunk_id"]
        if cid not in chunk_scores:
            chunk_scores[cid] = {
                "content": r["content"],
                "chunk_id": cid,
                "document_id": r["document_id"],
                "dense_score": r["score"],
                "sparse_score": None,
                "combined_score": 0.0,
            }
        chunk_scores[cid]["dense_score"] = r["score"]
        chunk_scores[cid]["combined_score"] += req.alpha * (1.0 / (RRF_K + rank + 1))

    for rank, r in enumerate(sparse_results):
        cid = r["chunk_id"]
        if cid not in chunk_scores:
            chunk_scores[cid] = {
                "content": r["content"],
                "chunk_id": cid,
                "document_id": r["document_id"],
                "dense_score": None,
                "sparse_score": r["score"],
                "combined_score": 0.0,
            }
        chunk_scores[cid]["sparse_score"] = r["score"]
        chunk_scores[cid]["combined_score"] += (1.0 - req.alpha) * (1.0 / (RRF_K + rank + 1))

    # Sort by combined score descending, take top_k
    merged = sorted(chunk_scores.values(), key=lambda x: x["combined_score"], reverse=True)[:req.top_k]

    return {"results": merged, "query": req.query, "top_k": req.top_k, "alpha": req.alpha}


# --- Test Set Routes ---


def _parse_test_question_row(row) -> dict:
    d = dict(row)
    rc = d.get("reference_contexts")
    d["reference_contexts"] = json.loads(rc) if rc else []
    return d


@app.post("/api/projects/{project_id}/test-sets", status_code=201)
async def create_test_set(project_id: int, req: TestSetCreate):
    from ragas_test.testgen import generate_project_testset

    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project exists
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate chunk_config_id belongs to project
    cc = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if cc is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    # Fetch chunks for this config
    chunk_rows = conn.execute(
        "SELECT content FROM chunks WHERE chunk_config_id = ?",
        (req.chunk_config_id,),
    ).fetchall()
    if not chunk_rows:
        raise HTTPException(
            status_code=422,
            detail="No chunks found for this config. Generate chunks first.",
        )

    # Guard: chunk count limit
    if len(chunk_rows) > MAX_CHUNKS_FOR_GENERATION:
        raise HTTPException(
            status_code=422,
            detail=f"Too many chunks ({len(chunk_rows)}). Maximum {MAX_CHUNKS_FOR_GENERATION} supported for test generation.",
        )

    chunks = [r["content"] for r in chunk_rows]

    # Auto-generate name if not provided
    name = req.name or f"Test Set ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

    # Insert test_set row
    generation_config = {
        "chunk_config_id": req.chunk_config_id,
        "testset_size": req.testset_size,
        "num_personas": req.num_personas,
        "custom_personas": req.custom_personas,
        "use_personas": req.use_personas,
    }
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
        (project_id, name, json.dumps(generation_config)),
    )
    conn.commit()
    test_set_id = cursor.lastrowid

    # Generate questions — rollback test_set on failure
    try:
        result = await generate_project_testset(
            chunks=chunks,
            testset_size=req.testset_size,
            use_personas=req.use_personas,
            num_personas=req.num_personas,
            custom_personas=req.custom_personas,
        )
    except Exception as e:
        # Rollback: remove the test_set row so no orphan persists
        conn.execute("DELETE FROM test_sets WHERE id = ?", (test_set_id,))
        conn.commit()
        err_msg = str(e).lower()
        if "rate limit" in err_msg or "rate_limit" in err_msg:
            raise HTTPException(status_code=429, detail="LLM rate limit exceeded during test generation")
        logger.exception("Test set generation failed for test_set_id=%d", test_set_id)
        raise HTTPException(status_code=502, detail=f"Test generation failed: {e}")

    # Insert questions
    questions = result.get("questions", [])
    personas = result.get("personas", [])
    persona_map = {p["name"]: p for p in personas} if personas else {}

    inserted_questions = []
    for q in questions:
        persona_name = q.get("persona") or (q.get("synthesizer_name") if not persona_map else None)
        conn.execute(
            """INSERT INTO test_questions
               (test_set_id, question, reference_answer, reference_contexts, question_type, persona, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (
                test_set_id,
                q.get("user_input", ""),
                q.get("reference", ""),
                json.dumps(q.get("reference_contexts", [])),
                q.get("synthesizer_name", ""),
                persona_name,
            ),
        )
        inserted_questions.append({
            "question": q.get("user_input", ""),
            "reference_answer": q.get("reference", ""),
            "reference_contexts": q.get("reference_contexts", []),
            "question_type": q.get("synthesizer_name", ""),
            "persona": persona_name,
            "status": "pending",
        })
    conn.commit()

    return {
        "id": test_set_id,
        "name": name,
        "project_id": project_id,
        "question_count": len(inserted_questions),
        "personas": personas,
        "questions": inserted_questions,
    }


@app.get("/api/projects/{project_id}/test-sets")
async def list_test_sets(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        """SELECT ts.id, ts.name, ts.generation_config_json, ts.created_at,
                  COUNT(tq.id) AS total_questions,
                  SUM(CASE WHEN tq.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                  SUM(CASE WHEN tq.status = 'approved' THEN 1 ELSE 0 END) AS approved_count,
                  SUM(CASE WHEN tq.status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count
           FROM test_sets ts
           LEFT JOIN test_questions tq ON tq.test_set_id = ts.id
           WHERE ts.project_id = ?
           GROUP BY ts.id
           ORDER BY ts.created_at DESC""",
        (project_id,),
    ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        gcj = d.pop("generation_config_json", None)
        d["generation_config"] = json.loads(gcj) if gcj else None
        result.append(d)

    return {"test_sets": result}


@app.get("/api/projects/{project_id}/test-sets/{test_set_id}/questions")
async def list_test_questions(project_id: int, test_set_id: int, status: str | None = None):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate status param
    if status is not None and status not in VALID_QUESTION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_QUESTION_STATUSES))}",
        )

    # Validate test set belongs to project
    ts = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
    ).fetchone()
    if ts is None:
        raise HTTPException(status_code=404, detail="Test set not found")

    query = "SELECT * FROM test_questions WHERE test_set_id = ?"
    params: list = [test_set_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id"

    rows = conn.execute(query, params).fetchall()
    return {"questions": [_parse_test_question_row(r) for r in rows]}


@app.delete("/api/projects/{project_id}/test-sets/{test_set_id}", status_code=204)
async def delete_test_set(project_id: int, test_set_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate test set belongs to project
    ts = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
    ).fetchone()
    if ts is None:
        raise HTTPException(status_code=404, detail="Test set not found")

    # Check referential integrity — cannot delete if experiments reference this test set
    exp = conn.execute(
        "SELECT id FROM experiments WHERE test_set_id = ?",
        (test_set_id,),
    ).fetchone()
    if exp is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete test set referenced by experiments",
        )

    conn.execute("DELETE FROM test_sets WHERE id = ?", (test_set_id,))
    conn.commit()
    return None


# --- Annotation Routes ---


@app.patch("/api/projects/{project_id}/test-sets/{test_set_id}/questions/{question_id}")
async def annotate_question(project_id: int, test_set_id: int, question_id: int, req: QuestionAnnotation):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project exists
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate test set belongs to project
    ts = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
    ).fetchone()
    if ts is None:
        raise HTTPException(status_code=404, detail="Test set not found")

    # Validate question belongs to test set
    question = conn.execute(
        "SELECT id FROM test_questions WHERE id = ? AND test_set_id = ?",
        (question_id, test_set_id),
    ).fetchone()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    # If status='edited', user_edited_answer is required
    if req.status == "edited" and not req.user_edited_answer:
        raise HTTPException(
            status_code=422,
            detail="user_edited_answer required when status is 'edited'",
        )

    # Update question
    conn.execute(
        """UPDATE test_questions
           SET status = ?, user_edited_answer = ?, user_notes = ?, reviewed_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (req.status, req.user_edited_answer, req.user_notes, question_id),
    )
    conn.commit()

    # Re-read from DB to return truth
    updated = conn.execute("SELECT * FROM test_questions WHERE id = ?", (question_id,)).fetchone()
    return _parse_test_question_row(updated)


@app.post("/api/projects/{project_id}/test-sets/{test_set_id}/questions/bulk")
async def bulk_annotate_questions(project_id: int, test_set_id: int, req: BulkAnnotation):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project exists
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate test set belongs to project
    ts = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
    ).fetchone()
    if ts is None:
        raise HTTPException(status_code=404, detail="Test set not found")

    target_status = BULK_ACTION_TO_STATUS[req.action]

    if req.action in ("approve", "reject"):
        # Require non-empty question_ids
        if not req.question_ids:
            raise HTTPException(
                status_code=422,
                detail="question_ids must not be empty for approve/reject actions",
            )

        # Validate all question_ids belong to this test set (parameterized query)
        placeholders = ",".join("?" * len(req.question_ids))
        valid_rows = conn.execute(
            f"SELECT id FROM test_questions WHERE id IN ({placeholders}) AND test_set_id = ?",
            (*req.question_ids, test_set_id),
        ).fetchall()
        valid_ids = {r["id"] for r in valid_rows}
        invalid_ids = [qid for qid in req.question_ids if qid not in valid_ids]
        if invalid_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Question IDs not found in this test set: {invalid_ids}",
            )

        # Update specified questions
        cursor = conn.execute(
            f"UPDATE test_questions SET status = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders}) AND test_set_id = ?",
            (target_status, *req.question_ids, test_set_id),
        )
        conn.commit()
        updated_count = cursor.rowcount

    elif req.action in ("approve_all", "reject_all"):
        # question_ids must be absent or empty
        if req.question_ids:
            raise HTTPException(
                status_code=422,
                detail=f"question_ids must not be provided for {req.action} action",
            )

        # Update all pending questions in this test set
        cursor = conn.execute(
            "UPDATE test_questions SET status = ?, reviewed_at = CURRENT_TIMESTAMP WHERE test_set_id = ? AND status = 'pending'",
            (target_status, test_set_id),
        )
        conn.commit()
        updated_count = cursor.rowcount

    return {"updated_count": updated_count}


@app.get("/api/projects/{project_id}/test-sets/{test_set_id}/summary")
async def test_set_summary(project_id: int, test_set_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project exists
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate test set belongs to project
    ts = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
    ).fetchone()
    if ts is None:
        raise HTTPException(status_code=404, detail="Test set not found")

    # Aggregate counts by status
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? GROUP BY status",
        (test_set_id,),
    ).fetchall()

    counts = {"pending": 0, "approved": 0, "rejected": 0, "edited": 0}
    for row in rows:
        s = row["status"]
        if s in counts:
            counts[s] = row["cnt"]

    total = sum(counts.values())
    completion_pct = round(((counts["approved"] + counts["edited"]) / total) * 100, 1) if total > 0 else 0.0

    return {
        "test_set_id": test_set_id,
        "total": total,
        **counts,
        "completion_pct": completion_pct,
    }


# --- Experiment Routes ---


def _parse_experiment_row(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "test_set_id": row["test_set_id"],
        "name": row["name"],
        "model": row["model"],
        "model_params": json.loads(row["model_params_json"]) if row["model_params_json"] else None,
        "retrieval_config": json.loads(row["retrieval_config_json"]) if row["retrieval_config_json"] else None,
        "chunk_config_id": row["chunk_config_id"],
        "embedding_config_id": row["embedding_config_id"],
        "rag_config_id": row["rag_config_id"],
        "baseline_experiment_id": row["baseline_experiment_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
    }


@app.post("/api/projects/{project_id}/experiments", status_code=201)
async def create_experiment(project_id: int, req: ExperimentCreate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate project exists
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate rag_config belongs to project
    rag_config = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (req.rag_config_id, project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(
            status_code=422,
            detail="RAG config not found in this project",
        )

    # Validate test_set belongs to project
    test_set = conn.execute(
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (req.test_set_id, project_id),
    ).fetchone()
    if test_set is None:
        raise HTTPException(
            status_code=422,
            detail="Test set not found in this project",
        )

    # Check that test set has approved/edited questions
    approved_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
        (req.test_set_id,),
    ).fetchone()["cnt"]
    if approved_count == 0:
        raise HTTPException(
            status_code=422,
            detail="Test set has no approved questions",
        )

    # Snapshot config from rag_config for reproducibility
    retrieval_config = json.dumps({
        "search_type": rag_config["search_type"],
        "sparse_config_id": rag_config["sparse_config_id"],
        "alpha": rag_config["alpha"],
        "top_k": rag_config["top_k"],
        "system_prompt": rag_config["system_prompt"],
        "response_mode": rag_config["response_mode"],
        "max_steps": rag_config["max_steps"],
    })

    cursor = conn.execute(
        """INSERT INTO experiments
           (project_id, test_set_id, name, model, model_params_json, retrieval_config_json,
            chunk_config_id, embedding_config_id, rag_config_id, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            project_id,
            req.test_set_id,
            req.name,
            rag_config["llm_model"],
            rag_config["llm_params_json"],
            retrieval_config,
            rag_config["chunk_config_id"],
            rag_config["embedding_config_id"],
            req.rag_config_id,
        ),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM experiments WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _parse_experiment_row(row)


@app.get("/api/projects/{project_id}/experiments")
async def list_experiments(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()

    experiments = []
    for row in rows:
        exp = _parse_experiment_row(row)
        # Include approved question count from the referenced test set
        q_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
            (row["test_set_id"],),
        ).fetchone()["cnt"]
        exp["approved_question_count"] = q_count
        experiments.append(exp)

    return experiments


# --- Experiment Comparison Route (must precede /{experiment_id} routes) ---


@app.get("/api/projects/{project_id}/experiments/compare")
async def compare_experiments(project_id: int, ids: str = Query(..., description="Comma-separated experiment IDs (2-5)")):
    # Parse and validate IDs
    raw_parts = ids.split(",")
    try:
        experiment_ids = [int(p.strip()) for p in raw_parts if p.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="All experiment IDs must be numeric")

    if len(experiment_ids) < 2 or len(experiment_ids) > 5:
        raise HTTPException(status_code=400, detail="Provide between 2 and 5 experiment IDs")

    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch all experiments with parameterized IN clause
    placeholders = ",".join("?" for _ in experiment_ids)
    rows = conn.execute(
        f"SELECT * FROM experiments WHERE id IN ({placeholders}) AND project_id = ?",
        (*experiment_ids, project_id),
    ).fetchall()

    if len(rows) != len(experiment_ids):
        found_ids = {r["id"] for r in rows}
        missing = [eid for eid in experiment_ids if eid not in found_ids]
        raise HTTPException(status_code=404, detail=f"Experiments not found in this project: {missing}")

    # Validate all completed
    non_completed = [r["id"] for r in rows if r["status"] != "completed"]
    if non_completed:
        raise HTTPException(
            status_code=409,
            detail=f"All experiments must be completed. Not completed: {non_completed}",
        )

    # Validate same test set
    test_set_ids = {r["test_set_id"] for r in rows}
    if len(test_set_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail="All experiments must use the same test set for comparison",
        )

    # Build experiment metadata
    experiments_meta = []
    for row in rows:
        exp = _parse_experiment_row(row)

        ts = conn.execute("SELECT name FROM test_sets WHERE id = ?", (row["test_set_id"],)).fetchone()
        exp["test_set_name"] = ts["name"] if ts else None

        if row["rag_config_id"]:
            rc = conn.execute("SELECT name FROM rag_configs WHERE id = ?", (row["rag_config_id"],)).fetchone()
            exp["rag_config_name"] = rc["name"] if rc else None
        else:
            exp["rag_config_name"] = None

        # Compute aggregate metrics
        result_rows = conn.execute(
            "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
            (row["id"],),
        ).fetchall()
        exp["result_count"] = len(result_rows)

        if result_rows:
            metric_totals = {}
            metric_counts = {}
            for rr in result_rows:
                metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
                for metric_name, value in metrics.items():
                    if value is not None:
                        metric_totals[metric_name] = metric_totals.get(metric_name, 0.0) + value
                        metric_counts[metric_name] = metric_counts.get(metric_name, 0) + 1
                    else:
                        if metric_name not in metric_totals:
                            metric_totals[metric_name] = 0.0
                        if metric_name not in metric_counts:
                            metric_counts[metric_name] = 0
            aggregate = {}
            for mn in metric_totals:
                cnt = metric_counts[mn]
                aggregate[mn] = round(metric_totals[mn] / cnt, 4) if cnt > 0 else None
            exp["aggregate_metrics"] = aggregate
        else:
            exp["aggregate_metrics"] = None

        experiments_meta.append(exp)

    # Fetch all results for all experiments with parameterized IN clause
    all_results = conn.execute(
        f"""SELECT er.*, tq.question, tq.reference_answer, tq.user_edited_answer,
                   tq.question_type, tq.persona
            FROM experiment_results er
            JOIN test_questions tq ON er.test_question_id = tq.id
            WHERE er.experiment_id IN ({placeholders})
            ORDER BY tq.id""",
        tuple(experiment_ids),
    ).fetchall()

    # Guard: payload size limit
    if len(all_results) > 2500:
        raise HTTPException(
            status_code=413,
            detail="Too many results for comparison. Reduce experiment count or use experiments with smaller test sets.",
        )

    # Build per-question aligned data
    questions_map = {}  # test_question_id -> { question info + per-experiment data }
    for r in all_results:
        qid = r["test_question_id"]
        if qid not in questions_map:
            ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
            questions_map[qid] = {
                "test_question_id": qid,
                "question": r["question"],
                "reference_answer": ref_answer,
                "question_type": r["question_type"],
                "persona": r["persona"],
                "experiments": {},
            }

        questions_map[qid]["experiments"][r["experiment_id"]] = {
            "response": r["response"],
            "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else {},
            "retrieved_contexts": json.loads(r["retrieved_contexts"]) if r["retrieved_contexts"] else [],
            "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
        }

    # Convert to ordered list
    questions_list = sorted(questions_map.values(), key=lambda q: q["test_question_id"])

    return {"experiments": experiments_meta, "questions": questions_list}


# --- Experiment History Route (must precede /{experiment_id} routes) ---


@app.get("/api/projects/{project_id}/experiments/history")
async def get_experiment_history(project_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        "SELECT * FROM experiments WHERE project_id = ? AND status = 'completed' ORDER BY completed_at DESC",
        (project_id,),
    ).fetchall()

    experiments = []
    for row in rows:
        exp = _parse_experiment_row(row)

        # Fetch rag_config_name
        if row["rag_config_id"]:
            rc = conn.execute("SELECT name FROM rag_configs WHERE id = ?", (row["rag_config_id"],)).fetchone()
            exp["rag_config_name"] = rc["name"] if rc else None
        else:
            exp["rag_config_name"] = None

        # Compute aggregate metrics and overall score
        result_rows = conn.execute(
            "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
            (row["id"],),
        ).fetchall()
        exp["result_count"] = len(result_rows)

        if result_rows:
            metric_totals = {}
            metric_counts = {}
            for rr in result_rows:
                metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
                for metric_name, value in metrics.items():
                    if value is not None:
                        metric_totals[metric_name] = metric_totals.get(metric_name, 0.0) + value
                        metric_counts[metric_name] = metric_counts.get(metric_name, 0) + 1

            aggregate = {}
            for mn in metric_totals:
                cnt = metric_counts[mn]
                aggregate[mn] = round(metric_totals[mn] / cnt, 4) if cnt > 0 else None

            exp["aggregate_metrics"] = aggregate

            # Overall score = average of all non-null metric averages
            valid_scores = [v for v in aggregate.values() if v is not None]
            exp["overall_score"] = round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
        else:
            exp["aggregate_metrics"] = None
            exp["overall_score"] = None

        experiments.append(exp)

    return {"experiments": experiments}


@app.get("/api/projects/{project_id}/experiments/{experiment_id}")
async def get_experiment(project_id: int, experiment_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    exp = _parse_experiment_row(row)

    # Include test_set name and rag_config name for display
    ts = conn.execute("SELECT name FROM test_sets WHERE id = ?", (row["test_set_id"],)).fetchone()
    exp["test_set_name"] = ts["name"] if ts else None

    if row["rag_config_id"]:
        rc = conn.execute("SELECT name FROM rag_configs WHERE id = ?", (row["rag_config_id"],)).fetchone()
        exp["rag_config_name"] = rc["name"] if rc else None
    else:
        exp["rag_config_name"] = None

    # Include approved question count
    q_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited')",
        (row["test_set_id"],),
    ).fetchone()["cnt"]
    exp["approved_question_count"] = q_count

    # Include result count and aggregate metrics
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()

    exp["result_count"] = len(result_rows)

    if result_rows:
        metric_totals = {}
        metric_counts = {}
        for rr in result_rows:
            metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
            for metric_name, value in metrics.items():
                if value is not None:
                    metric_totals[metric_name] = metric_totals.get(metric_name, 0.0) + value
                    metric_counts[metric_name] = metric_counts.get(metric_name, 0) + 1
                else:
                    # Ensure metric appears even if all null
                    if metric_name not in metric_totals:
                        metric_totals[metric_name] = 0.0
                    if metric_name not in metric_counts:
                        metric_counts[metric_name] = 0

        aggregate = {}
        for metric_name in metric_totals:
            count = metric_counts[metric_name]
            if count > 0:
                aggregate[metric_name] = round(metric_totals[metric_name] / count, 4)
            else:
                aggregate[metric_name] = None
        exp["aggregate_metrics"] = aggregate
    else:
        exp["aggregate_metrics"] = None

    return exp


@app.get("/api/projects/{project_id}/experiments/{experiment_id}/results")
async def get_experiment_results(project_id: int, experiment_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    rows = conn.execute(
        """SELECT er.*, tq.question, tq.reference_answer, tq.user_edited_answer,
                  tq.question_type, tq.persona
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id""",
        (experiment_id,),
    ).fetchall()

    results = []
    for r in rows:
        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        results.append({
            "id": r["id"],
            "test_question_id": r["test_question_id"],
            "question": r["question"],
            "reference_answer": ref_answer,
            "question_type": r["question_type"],
            "persona": r["persona"],
            "response": r["response"],
            "retrieved_contexts": json.loads(r["retrieved_contexts"]) if r["retrieved_contexts"] else [],
            "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else {},
            "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
            "created_at": r["created_at"],
        })

    return results


@app.delete("/api/projects/{project_id}/experiments/{experiment_id}", status_code=204)
async def delete_experiment(project_id: int, experiment_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete experiment with status '{row['status']}'. Only pending experiments can be deleted.",
        )

    conn.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))
    conn.commit()
    return None


# --- Model Registry Route ---


@app.get("/api/models")
async def get_models():
    from llm.connector import list_providers
    return list_providers()


# --- Experiment Runner Route ---


@app.post("/api/projects/{project_id}/experiments/{experiment_id}/run")
async def run_experiment(project_id: int, experiment_id: int, req: ExperimentRunRequest):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Pre-validation (non-authoritative — atomic guard is inside generator)
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["status"] not in ("pending", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Experiment already {experiment['status']}. Only pending or failed experiments can be run.",
        )

    # Note: rag_config may have been deleted after experiment creation.
    # All config is snapshotted in the experiment row; project_id comes from URL.

    # Silently filter metrics to valid ones
    requested_metrics = req.metrics if req.metrics else DEFAULT_EXPERIMENT_METRICS
    selected_metrics = [m for m in requested_metrics if m in ALL_METRICS]
    if not selected_metrics:
        raise HTTPException(status_code=400, detail="No valid metrics selected")

    async def _run_generator():
        run_conn = get_db_conn()
        run_conn.row_factory = sqlite3.Row
        completed_count = 0

        try:
            # Atomic status claim — prevents concurrent run race condition
            cursor = run_conn.execute(
                "UPDATE experiments SET status = 'running', started_at = ? WHERE id = ? AND status IN ('pending', 'failed')",
                (datetime.utcnow().isoformat(), experiment_id),
            )
            run_conn.commit()

            if cursor.rowcount != 1:
                yield f"event: error\ndata: {json.dumps({'message': 'Experiment already claimed by another request'})}\n\n"
                return

            # Clean up partial results from prior failed run (if any)
            deleted = run_conn.execute(
                "DELETE FROM experiment_results WHERE experiment_id = ?", (experiment_id,)
            )
            if deleted.rowcount > 0:
                run_conn.commit()
                logger.info("Experiment %d re-run: deleted %d partial results from prior attempt", experiment_id, deleted.rowcount)

            # Fetch approved/edited test questions
            questions = run_conn.execute(
                "SELECT * FROM test_questions WHERE test_set_id = ? AND status IN ('approved', 'edited') ORDER BY id",
                (experiment["test_set_id"],),
            ).fetchall()

            total = len(questions)
            yield f"event: started\ndata: {json.dumps({'experiment_id': experiment_id, 'total_questions': total, 'metrics': selected_metrics})}\n\n"

            # Setup scorers
            scorers = setup_scorers(selected_metrics)

            # Build virtual rag_config row (uses snapshotted config + URL project_id)
            virtual_config = _build_virtual_rag_config_row(experiment, project_id)
            response_mode = virtual_config["response_mode"]

            for i, q_row in enumerate(questions, 1):
                question_text = q_row["question"]
                qid = q_row["id"]

                try:
                    # Execute RAG query
                    if response_mode == "multi_step":
                        query_result = await multi_step_query(question_text, virtual_config, run_conn)
                    else:
                        query_result = await single_shot_query(question_text, virtual_config, run_conn)

                    generated_answer = query_result["answer"]
                    full_context_dicts = query_result["contexts"]
                    usage_info = query_result.get("usage", {})

                    # Extract content strings for metric evaluation
                    context_strings = [c["content"] for c in full_context_dicts]

                    # Get reference answer (prefer user-edited)
                    ref_answer = q_row["user_edited_answer"] if q_row["user_edited_answer"] else q_row["reference_answer"]

                    # Evaluate metrics
                    metrics_result = await _evaluate_experiment_row(
                        scorers, question_text, generated_answer, ref_answer, context_strings,
                    )

                    # Store result
                    run_conn.execute(
                        """INSERT INTO experiment_results
                           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            experiment_id,
                            qid,
                            generated_answer,
                            json.dumps(full_context_dicts),
                            json.dumps(metrics_result),
                            json.dumps(usage_info),
                        ),
                    )
                    run_conn.commit()
                    completed_count += 1

                    yield f"event: progress\ndata: {json.dumps({'current': i, 'total': total, 'question_id': qid, 'question': question_text[:100]})}\n\n"

                except Exception as e:
                    # Per-question error isolation: store error row, continue
                    logger.warning("Experiment %d question %d failed: %s", experiment_id, qid, e)
                    run_conn.execute(
                        """INSERT INTO experiment_results
                           (experiment_id, test_question_id, response, retrieved_contexts, metrics_json, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            experiment_id,
                            qid,
                            None,
                            "[]",
                            "{}",
                            json.dumps({"error": str(e), "question_id": qid}),
                        ),
                    )
                    run_conn.commit()
                    completed_count += 1

                    yield f"event: progress\ndata: {json.dumps({'current': i, 'total': total, 'question_id': qid, 'question': question_text[:100], 'error': str(e)})}\n\n"

            # All questions processed — mark completed
            run_conn.execute(
                "UPDATE experiments SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), experiment_id),
            )
            run_conn.commit()

            yield f"event: completed\ndata: {json.dumps({'experiment_id': experiment_id, 'result_count': completed_count})}\n\n"

        except Exception as e:
            logger.error("Experiment %d fatal error: %s", experiment_id, e)
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        finally:
            # Cleanup guarantee: if still "running", set to "failed"
            try:
                row = run_conn.execute(
                    "SELECT status FROM experiments WHERE id = ?", (experiment_id,)
                ).fetchone()
                if row and row["status"] == "running":
                    run_conn.execute(
                        "UPDATE experiments SET status = 'failed', completed_at = ? WHERE id = ?",
                        (datetime.utcnow().isoformat(), experiment_id),
                    )
                    run_conn.commit()
            except Exception:
                pass  # Best-effort cleanup

    return StreamingResponse(_run_generator(), media_type="text/event-stream")


@app.post("/api/projects/{project_id}/experiments/{experiment_id}/reset")
async def reset_experiment(project_id: int, experiment_id: int):
    """Reset a failed experiment so it can be re-run. Deletes partial results."""
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Atomic guard: only reset if status is 'failed' and belongs to project
    cursor = conn.execute(
        "UPDATE experiments SET status = 'pending', started_at = NULL, completed_at = NULL "
        "WHERE id = ? AND project_id = ? AND status = 'failed'",
        (experiment_id, project_id),
    )
    conn.commit()

    if cursor.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Only failed experiments can be reset.",
        )

    # Delete partial results
    deleted = conn.execute(
        "DELETE FROM experiment_results WHERE experiment_id = ?", (experiment_id,)
    )
    conn.commit()
    logger.info("Experiment %d reset: deleted %d partial results", experiment_id, deleted.rowcount)

    # Return updated experiment
    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
    ).fetchone()

    return {
        "id": experiment["id"],
        "project_id": experiment["project_id"],
        "test_set_id": experiment["test_set_id"],
        "rag_config_id": experiment["rag_config_id"],
        "name": experiment["name"],
        "model": experiment["model"],
        "status": experiment["status"],
        "created_at": experiment["created_at"],
        "started_at": experiment["started_at"],
        "completed_at": experiment["completed_at"],
    }


# --- Suggestion Engine Routes ---


def _generate_suggestions(aggregate_metrics: dict, per_question_results: list[dict]) -> list[dict]:
    """Rule-based suggestion engine: analyzes metrics and returns actionable suggestions."""
    suggestions = []

    if not aggregate_metrics:
        return suggestions

    def _priority(score):
        if score < 0.4:
            return "high"
        elif score < 0.7:
            return "medium"
        else:
            return "low"

    # --- Retrieval rules ---
    context_recall = aggregate_metrics.get("context_recall")
    if context_recall is not None and context_recall < 0.7:
        suggestions.append({
            "category": "retrieval",
            "signal": f"context_recall avg {context_recall:.2f}",
            "suggestion": "Consider increasing top_k, adding hybrid search, or re-chunking with smaller chunk sizes for better recall",
            "priority": _priority(context_recall),
            "config_field": "top_k",
            "suggested_value": "+5",
        })

    context_precision = aggregate_metrics.get("context_precision")
    if context_precision is not None and context_precision < 0.7:
        suggestions.append({
            "category": "retrieval",
            "signal": f"context_precision avg {context_precision:.2f}",
            "suggestion": "Retrieved contexts are noisy — try reranking, reduce top_k, or use more specific embedding model",
            "priority": _priority(context_precision),
            "config_field": "top_k",
            "suggested_value": "-2",
        })

    context_relevance = aggregate_metrics.get("context_relevance")
    if context_relevance is not None and context_relevance < 0.5:
        suggestions.append({
            "category": "retrieval",
            "signal": f"context_relevance avg {context_relevance:.2f}",
            "suggestion": "Contexts are not relevant — review embedding model choice or chunking strategy",
            "priority": _priority(context_relevance),
            "config_field": "embedding_config_id",
            "suggested_value": None,
        })

    # --- Generation rules ---
    faithfulness = aggregate_metrics.get("faithfulness")
    if faithfulness is not None and faithfulness < 0.7:
        suggestions.append({
            "category": "generation",
            "signal": f"faithfulness avg {faithfulness:.2f}",
            "suggestion": "Responses contain unsupported claims — add system prompt instruction to only use provided context",
            "priority": _priority(faithfulness),
            "config_field": "system_prompt",
            "suggested_value": None,
        })

    answer_relevancy = aggregate_metrics.get("answer_relevancy")
    if answer_relevancy is not None and answer_relevancy < 0.7:
        suggestions.append({
            "category": "generation",
            "signal": f"answer_relevancy avg {answer_relevancy:.2f}",
            "suggestion": "Responses are not addressing the question — check system prompt clarity and response_mode",
            "priority": _priority(answer_relevancy),
            "config_field": "response_mode",
            "suggested_value": "multi_step",
        })

    answer_correctness = aggregate_metrics.get("answer_correctness")
    if answer_correctness is not None and answer_correctness < 0.5:
        suggestions.append({
            "category": "generation",
            "signal": f"answer_correctness avg {answer_correctness:.2f}",
            "suggestion": "Low correctness — verify reference answers are accurate, then review retrieval quality",
            "priority": _priority(answer_correctness),
            "config_field": None,
            "suggested_value": None,
        })

    # --- Embedding rules (cross-metric) ---
    if (context_recall is not None and context_recall < 0.5
            and context_precision is not None and context_precision < 0.5):
        suggestions.append({
            "category": "embedding",
            "signal": f"context_recall {context_recall:.2f} AND context_precision {context_precision:.2f}",
            "suggestion": "Both recall and precision low — embedding model may be mismatched for this domain. Try a different model or fine-tune",
            "priority": "high",
            "config_field": "embedding_config_id",
            "suggested_value": None,
        })

    # --- Chunking rules (variance-based) ---
    if per_question_results:
        # Collect per-question scores for each metric
        metric_scores: dict[str, list[float]] = {}
        for r in per_question_results:
            metrics = r.get("metrics", {})
            for mn, val in metrics.items():
                if val is not None:
                    metric_scores.setdefault(mn, []).append(val)

        for mn, scores in metric_scores.items():
            if len(scores) >= 3:  # Need at least 3 data points for meaningful stdev
                stdev = statistics.stdev(scores)
                if stdev > 0.3:
                    suggestions.append({
                        "category": "chunking",
                        "signal": f"{mn} stdev {stdev:.2f} across {len(scores)} questions",
                        "suggestion": f"High variance in {mn} — inconsistent chunk quality. Review chunking strategy for uniformity",
                        "priority": "medium",
                        "config_field": "chunk_config_id",
                        "suggested_value": None,
                    })

    return suggestions


@app.post("/api/projects/{project_id}/experiments/{experiment_id}/suggestions/generate")
async def generate_suggestions(project_id: int, experiment_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["status"] != "completed":
        raise HTTPException(status_code=409, detail="Experiment must be completed to generate suggestions")

    # Fetch results
    result_rows = conn.execute(
        "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()

    if not result_rows:
        raise HTTPException(status_code=409, detail="No results to analyze")

    # Compute aggregate metrics
    metric_totals = {}
    metric_counts = {}
    per_question_results = []
    for rr in result_rows:
        metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
        per_question_results.append({"metrics": metrics})
        for metric_name, value in metrics.items():
            if value is not None:
                metric_totals[metric_name] = metric_totals.get(metric_name, 0.0) + value
                metric_counts[metric_name] = metric_counts.get(metric_name, 0) + 1

    aggregate = {}
    for mn in metric_totals:
        cnt = metric_counts[mn]
        aggregate[mn] = round(metric_totals[mn] / cnt, 4) if cnt > 0 else None

    # Generate suggestions
    new_suggestions = _generate_suggestions(aggregate, per_question_results)

    # Atomic: delete old + insert new in single transaction
    conn.execute("DELETE FROM suggestions WHERE experiment_id = ?", (experiment_id,))
    for s in new_suggestions:
        conn.execute(
            "INSERT INTO suggestions (experiment_id, category, signal, suggestion, priority, config_field, suggested_value) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (experiment_id, s["category"], s["signal"], s["suggestion"], s["priority"],
             s.get("config_field"), s.get("suggested_value")),
        )
    conn.commit()

    # Re-read from DB to return actual state
    rows = conn.execute(
        "SELECT * FROM suggestions WHERE experiment_id = ? ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, category",
        (experiment_id,),
    ).fetchall()
    result = [dict(r) for r in rows]

    return {"suggestions": result, "count": len(result)}


@app.get("/api/projects/{project_id}/experiments/{experiment_id}/suggestions")
async def get_suggestions(project_id: int, experiment_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT id FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    rows = conn.execute(
        "SELECT * FROM suggestions WHERE experiment_id = ? ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, category",
        (experiment_id,),
    ).fetchall()

    return {"suggestions": [dict(r) for r in rows]}


@app.patch("/api/projects/{project_id}/suggestions/{suggestion_id}")
async def update_suggestion(project_id: int, suggestion_id: int, req: SuggestionUpdate):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Single JOIN query for cross-project isolation
    row = conn.execute(
        """SELECT s.* FROM suggestions s
           JOIN experiments e ON s.experiment_id = e.id
           WHERE s.id = ? AND e.project_id = ?""",
        (suggestion_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    conn.execute(
        "UPDATE suggestions SET implemented = ? WHERE id = ?",
        (req.implemented, suggestion_id),
    )
    conn.commit()

    # Re-read from DB to return actual state
    updated = conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    return dict(updated)


# --- Apply Suggestion Route ---


# Fields where override_value must be validated as a specific type
_NUMERIC_CONFIG_FIELDS = {"top_k", "alpha", "max_steps"}
_ENUM_CONFIG_FIELDS = {
    "response_mode": VALID_RESPONSE_MODES,
    "search_type": VALID_SEARCH_TYPES,
}


def _apply_config_change(config_row: dict, config_field: str, suggested_value: str | None, override_value: str | None) -> tuple[dict, dict]:
    """Apply a suggestion's config change to a cloned config dict.

    Returns (updated_fields_dict, changes_dict) where changes_dict is {field: {old, new}}.
    """
    value_to_use = override_value if override_value is not None else suggested_value
    old_value = config_row.get(config_field)
    new_value = old_value  # default: no change

    if config_field == "top_k":
        current = config_row["top_k"]
        if value_to_use is not None and value_to_use.lstrip("+-").isdigit() and (value_to_use.startswith("+") or value_to_use.startswith("-")):
            # Relative change
            new_value = current + int(value_to_use)
        elif value_to_use is not None and value_to_use.isdigit():
            # Absolute value
            new_value = int(value_to_use)
        else:
            raise ValueError(f"Invalid top_k value: '{value_to_use}'. Use relative (+5, -2) or absolute (10) integer.")
        new_value = max(1, min(50, new_value))

    elif config_field == "max_steps":
        if value_to_use is None:
            raise ValueError("max_steps requires a value")
        try:
            new_value = int(value_to_use)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid max_steps value: '{value_to_use}'. Must be integer 1-10.")
        if new_value < 1 or new_value > 10:
            raise ValueError("max_steps must be between 1 and 10")

    elif config_field == "alpha":
        if value_to_use is None:
            raise ValueError("alpha requires a value")
        try:
            new_value = float(value_to_use)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid alpha value: '{value_to_use}'. Must be float 0.0-1.0.")
        if new_value < 0.0 or new_value > 1.0:
            raise ValueError("alpha must be between 0.0 and 1.0")

    elif config_field in _ENUM_CONFIG_FIELDS:
        allowed = _ENUM_CONFIG_FIELDS[config_field]
        if value_to_use is not None and value_to_use in allowed:
            new_value = value_to_use
        elif value_to_use is not None:
            raise ValueError(f"Invalid {config_field} value: '{value_to_use}'. Must be one of: {', '.join(sorted(allowed))}")
        else:
            raise ValueError(f"{config_field} requires a value. Provide override_value as one of: {', '.join(sorted(allowed))}")

    elif config_field == "system_prompt":
        if value_to_use is None:
            raise ValueError("system_prompt requires an override_value with the new prompt text")
        new_value = value_to_use

    elif config_field in ("embedding_config_id", "chunk_config_id"):
        if value_to_use is None:
            raise ValueError(f"{config_field} requires an override_value with the new config ID")
        try:
            new_value = int(value_to_use)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid {config_field} value: '{value_to_use}'. Must be an integer ID.")

    else:
        if value_to_use is not None:
            new_value = value_to_use

    changes = {config_field: {"old": old_value, "new": new_value}}
    return {config_field: new_value}, changes


@app.post("/api/projects/{project_id}/suggestions/{suggestion_id}/apply")
async def apply_suggestion(project_id: int, suggestion_id: int, req: ApplySuggestionRequest | None = None):
    if req is None:
        req = ApplySuggestionRequest()

    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    # Validate suggestion exists and belongs to project (JOIN through experiments)
    row = conn.execute(
        """SELECT s.*, e.id as exp_id, e.project_id as exp_project_id, e.rag_config_id as exp_rag_config_id,
                  e.test_set_id, e.model, e.model_params_json, e.retrieval_config_json,
                  e.chunk_config_id as exp_chunk_config_id, e.embedding_config_id as exp_embedding_config_id,
                  e.name as exp_name
           FROM suggestions s
           JOIN experiments e ON s.experiment_id = e.id
           WHERE s.id = ? AND e.project_id = ?""",
        (suggestion_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # Idempotency guard: check if already implemented
    if row["implemented"]:
        raise HTTPException(status_code=409, detail="Suggestion already applied")

    # Validate original experiment has a RAG config
    if row["exp_rag_config_id"] is None:
        raise HTTPException(status_code=409, detail="Original experiment has no RAG config")

    # Validate original RAG config still exists
    rag_config = conn.execute(
        "SELECT * FROM rag_configs WHERE id = ? AND project_id = ?",
        (row["exp_rag_config_id"], project_id),
    ).fetchone()
    if rag_config is None:
        raise HTTPException(status_code=409, detail="Original RAG config no longer exists")

    config_field = row["config_field"]
    suggested_value = row["suggested_value"]

    # If no config_field, require override_value with a field specification
    if config_field is None:
        raise HTTPException(
            status_code=400,
            detail="This suggestion has no direct config mapping. It requires manual review — no automatic config change can be applied.",
        )

    # Apply config change
    try:
        updated_fields, changes = _apply_config_change(
            dict(rag_config), config_field, suggested_value, req.override_value,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Count existing iterations for naming
    iteration_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM experiments WHERE baseline_experiment_id = ?",
        (row["exp_id"],),
    ).fetchone()["cnt"]

    new_config_name = f"{rag_config['name']} — iteration {iteration_count + 1}"
    new_experiment_name = req.experiment_name or f"{row['exp_name']} — iteration {iteration_count + 1}"

    # Atomic transaction: INSERT config + INSERT experiment + UPDATE suggestion
    try:
        # Clone RAG config with the change applied
        new_config_values = {
            "project_id": project_id,
            "name": new_config_name,
            "embedding_config_id": rag_config["embedding_config_id"],
            "chunk_config_id": rag_config["chunk_config_id"],
            "search_type": rag_config["search_type"],
            "sparse_config_id": rag_config["sparse_config_id"],
            "alpha": rag_config["alpha"],
            "llm_model": rag_config["llm_model"],
            "llm_params_json": rag_config["llm_params_json"],
            "top_k": rag_config["top_k"],
            "system_prompt": rag_config["system_prompt"],
            "response_mode": rag_config["response_mode"],
            "max_steps": rag_config["max_steps"],
        }
        # Apply the changed field(s)
        for field, value in updated_fields.items():
            if field == "llm_params":
                new_config_values["llm_params_json"] = json.dumps(value) if value else None
            else:
                new_config_values[field] = value

        cursor = conn.execute(
            """INSERT INTO rag_configs
               (project_id, name, embedding_config_id, chunk_config_id, search_type,
                sparse_config_id, alpha, llm_model, llm_params_json, top_k, system_prompt,
                response_mode, max_steps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_config_values["project_id"], new_config_values["name"],
             new_config_values["embedding_config_id"], new_config_values["chunk_config_id"],
             new_config_values["search_type"], new_config_values["sparse_config_id"],
             new_config_values["alpha"], new_config_values["llm_model"],
             new_config_values["llm_params_json"], new_config_values["top_k"],
             new_config_values["system_prompt"], new_config_values["response_mode"],
             new_config_values["max_steps"]),
        )
        new_config_id = cursor.lastrowid

        # Snapshot retrieval config from new RAG config
        retrieval_config = json.dumps({
            "search_type": new_config_values["search_type"],
            "sparse_config_id": new_config_values["sparse_config_id"],
            "alpha": new_config_values["alpha"],
            "top_k": new_config_values["top_k"],
            "system_prompt": new_config_values["system_prompt"],
            "response_mode": new_config_values["response_mode"],
            "max_steps": new_config_values["max_steps"],
        })

        cursor2 = conn.execute(
            """INSERT INTO experiments
               (project_id, test_set_id, name, model, model_params_json, retrieval_config_json,
                chunk_config_id, embedding_config_id, rag_config_id, baseline_experiment_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (project_id, row["test_set_id"], new_experiment_name, row["model"],
             row["model_params_json"], retrieval_config,
             new_config_values["chunk_config_id"], new_config_values["embedding_config_id"],
             new_config_id, row["exp_id"]),
        )
        new_experiment_id = cursor2.lastrowid

        # Mark suggestion as implemented
        conn.execute("UPDATE suggestions SET implemented = TRUE WHERE id = ?", (suggestion_id,))

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "experiment_id": new_experiment_id,
        "rag_config_id": new_config_id,
        "experiment_name": new_experiment_name,
        "config_changes": changes,
    }


# --- Delta Comparison Route ---


# RAG config fields to compare for delta (excludes internal fields like id, project_id, created_at)
_RAG_CONFIG_DIFF_FIELDS = [
    "name", "embedding_config_id", "chunk_config_id", "search_type",
    "sparse_config_id", "alpha", "llm_model", "top_k", "system_prompt",
    "response_mode", "max_steps",
]


@app.get("/api/projects/{project_id}/experiments/{experiment_id}/delta")
async def get_experiment_delta(project_id: int, experiment_id: int):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["baseline_experiment_id"] is None:
        raise HTTPException(status_code=404, detail="No baseline experiment — this experiment is not an iteration")

    baseline = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment["baseline_experiment_id"], project_id),
    ).fetchone()
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline experiment not found")

    # Validate same test set
    if experiment["test_set_id"] != baseline["test_set_id"]:
        raise HTTPException(
            status_code=409,
            detail="Baseline and iteration experiments use different test sets — delta comparison requires the same test set",
        )

    # Validate both completed
    if experiment["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Iteration experiment status is '{experiment['status']}', must be 'completed'")
    if baseline["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Baseline experiment status is '{baseline['status']}', must be 'completed'")

    # Compare RAG configs
    config_changes = []
    iter_config = None
    base_config = None
    if experiment["rag_config_id"]:
        iter_config = conn.execute("SELECT * FROM rag_configs WHERE id = ?", (experiment["rag_config_id"],)).fetchone()
    if baseline["rag_config_id"]:
        base_config = conn.execute("SELECT * FROM rag_configs WHERE id = ?", (baseline["rag_config_id"],)).fetchone()

    if iter_config and base_config:
        for field in _RAG_CONFIG_DIFF_FIELDS:
            old_val = base_config[field]
            new_val = iter_config[field]
            # Handle llm_params_json specially
            if field == "llm_params_json":
                old_val = json.loads(old_val) if old_val else None
                new_val = json.loads(new_val) if new_val else None
            if old_val != new_val:
                config_changes.append({"field": field, "old_value": old_val, "new_value": new_val})

    # Compute aggregate metrics for both
    def _compute_aggregates(exp_id):
        result_rows = conn.execute(
            "SELECT metrics_json FROM experiment_results WHERE experiment_id = ?", (exp_id,),
        ).fetchall()
        totals = {}
        counts = {}
        for rr in result_rows:
            metrics = json.loads(rr["metrics_json"]) if rr["metrics_json"] else {}
            for mn, val in metrics.items():
                if val is not None:
                    totals[mn] = totals.get(mn, 0.0) + val
                    counts[mn] = counts.get(mn, 0) + 1
        agg = {}
        for mn in totals:
            cnt = counts[mn]
            agg[mn] = round(totals[mn] / cnt, 4) if cnt > 0 else None
        return agg

    baseline_agg = _compute_aggregates(baseline["id"])
    iteration_agg = _compute_aggregates(experiment["id"])

    # Build metric_deltas
    all_metrics = set(baseline_agg.keys()) | set(iteration_agg.keys())
    metric_deltas = {}
    for mn in sorted(all_metrics):
        b_val = baseline_agg.get(mn)
        i_val = iteration_agg.get(mn)
        delta = None
        improved = None
        if b_val is not None and i_val is not None:
            delta = round(i_val - b_val, 4)
            improved = delta > 0
        metric_deltas[mn] = {
            "baseline": b_val,
            "iteration": i_val,
            "delta": delta,
            "improved": improved,
        }

    # Per-question deltas (aligned by test_question_id)
    baseline_results = conn.execute(
        """SELECT er.test_question_id, er.metrics_json, tq.question
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?""",
        (baseline["id"],),
    ).fetchall()
    iteration_results = conn.execute(
        """SELECT er.test_question_id, er.metrics_json
           FROM experiment_results er
           WHERE er.experiment_id = ?""",
        (experiment["id"],),
    ).fetchall()

    baseline_by_q = {r["test_question_id"]: r for r in baseline_results}
    iteration_by_q = {r["test_question_id"]: r for r in iteration_results}

    all_q_ids = sorted(set(baseline_by_q.keys()) | set(iteration_by_q.keys()))
    per_question_deltas = []
    for qid in all_q_ids:
        b_row = baseline_by_q.get(qid)
        i_row = iteration_by_q.get(qid)
        b_metrics = json.loads(b_row["metrics_json"]) if b_row and b_row["metrics_json"] else {}
        i_metrics = json.loads(i_row["metrics_json"]) if i_row and i_row["metrics_json"] else {}
        question_text = b_row["question"] if b_row else None

        q_metrics = {}
        for mn in sorted(set(b_metrics.keys()) | set(i_metrics.keys())):
            bv = b_metrics.get(mn)
            iv = i_metrics.get(mn)
            d = round(iv - bv, 4) if bv is not None and iv is not None else None
            q_metrics[mn] = {"baseline": bv, "iteration": iv, "delta": d}

        per_question_deltas.append({
            "test_question_id": qid,
            "question": question_text,
            "metrics": q_metrics,
        })

    return {
        "experiment_id": experiment["id"],
        "experiment_name": experiment["name"],
        "baseline_experiment_id": baseline["id"],
        "baseline_experiment_name": baseline["name"],
        "config_changes": config_changes,
        "metric_deltas": metric_deltas,
        "per_question_deltas": per_question_deltas,
    }


# --- Export Route ---


def _sanitize_csv_value(val: str) -> str:
    """Prevent CSV formula injection (CWE-1236) by prefixing dangerous characters."""
    if val and isinstance(val, str) and len(val) > 0 and val[0] in ("=", "+", "-", "@"):
        return "'" + val
    return val


@app.get("/api/projects/{project_id}/experiments/{experiment_id}/export")
async def export_experiment(project_id: int, experiment_id: int, format: str = Query("json", description="Export format: csv or json")):
    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")

    conn = get_db_conn()
    conn.row_factory = sqlite3.Row

    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Experiment status is '{experiment['status']}', must be 'completed' to export")

    # Fetch results
    rows = conn.execute(
        """SELECT er.*, tq.question, tq.reference_answer, tq.user_edited_answer
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?
           ORDER BY er.id""",
        (experiment_id,),
    ).fetchall()

    # Payload guard
    if len(rows) > 2500:
        raise HTTPException(status_code=413, detail="Too many results to export (max 2500)")

    # Fetch RAG config name for metadata
    rag_config_name = None
    if experiment["rag_config_id"]:
        rc = conn.execute("SELECT name FROM rag_configs WHERE id = ?", (experiment["rag_config_id"],)).fetchone()
        rag_config_name = rc["name"] if rc else None

    # Build export data
    # Collect all metric names across all results
    all_metric_names: set[str] = set()
    parsed_rows = []
    for r in rows:
        ref_answer = r["user_edited_answer"] if r["user_edited_answer"] else r["reference_answer"]
        metrics = json.loads(r["metrics_json"]) if r["metrics_json"] else {}
        all_metric_names.update(metrics.keys())
        parsed_rows.append({
            "question": r["question"],
            "reference_answer": ref_answer,
            "response": r["response"],
            "metrics": metrics,
        })

    sorted_metrics = sorted(all_metric_names)

    # Build filename
    safe_name = experiment["name"].replace(" ", "_").replace("/", "_")[:50]
    date_str = (experiment["completed_at"] or experiment["created_at"] or "")[:10]

    if format == "json":
        export_data = []
        for pr in parsed_rows:
            row_data = {
                "question": pr["question"],
                "reference_answer": pr["reference_answer"],
                "response": pr["response"],
            }
            for mn in sorted_metrics:
                row_data[mn] = pr["metrics"].get(mn)
            row_data["experiment_name"] = experiment["name"]
            row_data["model"] = experiment["model"]
            row_data["rag_config"] = rag_config_name
            export_data.append(row_data)

        content = json.dumps(export_data, indent=2)
        filename = f"{safe_name}_{date_str}.json"
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    else:  # csv
        output = io.StringIO()
        fieldnames = ["question", "reference_answer", "response"] + sorted_metrics + ["experiment_name", "model", "rag_config"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for pr in parsed_rows:
            row_data = {
                "question": _sanitize_csv_value(pr["question"]),
                "reference_answer": _sanitize_csv_value(pr["reference_answer"]),
                "response": _sanitize_csv_value(pr["response"]),
            }
            for mn in sorted_metrics:
                row_data[mn] = pr["metrics"].get(mn)
            row_data["experiment_name"] = _sanitize_csv_value(experiment["name"])
            row_data["model"] = experiment["model"]
            row_data["rag_config"] = _sanitize_csv_value(rag_config_name or "")
            writer.writerow(row_data)

        csv_content = output.getvalue()
        filename = f"{safe_name}_{date_str}.csv"
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


# SPA catch-all: serve index.html for any /app/* route that isn't a static asset
_frontend_dist = Path("frontend/dist")
if _frontend_dist.is_dir():
    # Serve static assets (JS, CSS, images) from the build
    app.mount("/app/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets")

    @app.get("/app/{path:path}")
    async def spa_fallback(path: str):
        """Serve index.html for all SPA routes (React Router handles client-side routing)."""
        return FileResponse(str(_frontend_dist / "index.html"))

    @app.get("/")
    async def root_redirect():
        """Redirect root to the React SPA."""
        return RedirectResponse(url="/app/setup")
else:
    @app.get("/")
    async def root_redirect_no_build():
        """Redirect root even without frontend build."""
        return RedirectResponse(url="/app/setup")
