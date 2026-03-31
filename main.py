import argparse
import asyncio
import csv
import io
import json
import logging
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory

from chunking import chunk_text_pipeline
from db.init import get_db as get_db_conn
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
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

CONTEXT_SEPARATOR = "||"

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


async def evaluate_row(scorers, question: str, answer: str, contexts: list[str]) -> dict:
    results = {}

    for name, scorer in scorers.items():
        try:
            if name == "faithfulness":
                results[name] = await faithfulness.score(scorer, question, answer, contexts)
            elif name == "answer_relevancy":
                results[name] = await answer_relevancy.score(scorer, question, answer)
            elif name == "context_precision":
                results[name] = await context_precision.score(scorer, question, answer, contexts)
            elif name == "context_recall":
                results[name] = await context_recall.score(scorer, question, answer, contexts)
            elif name == "context_entities_recall":
                results[name] = await context_entities_recall.score(scorer, answer, contexts)
            elif name == "noise_sensitivity":
                results[name] = await noise_sensitivity.score(scorer, question, answer, answer, contexts)
            elif name == "factual_correctness":
                results[name] = await factual_correctness.score(scorer, answer, answer)
            elif name == "semantic_similarity":
                results[name] = await semantic_similarity.score(scorer, answer, answer)
            elif name == "non_llm_string_similarity":
                results[name] = await non_llm_string_similarity.score(scorer, answer, answer)
            elif name == "bleu_score":
                results[name] = await bleu_score.score(scorer, answer, answer)
            elif name == "rouge_score":
                results[name] = await rouge_score.score(scorer, answer, answer)
            elif name == "chrf_score":
                results[name] = await chrf_score.score(scorer, answer, answer)
            elif name == "exact_match":
                results[name] = await exact_match.score(scorer, answer, answer)
            elif name == "string_presence":
                results[name] = await string_presence.score(scorer, answer, answer)
            elif name == "summarization_score":
                results[name] = await summarization_score.score(scorer, answer, contexts)
            elif name == "aspect_critic":
                results[name] = await aspect_critic.score(scorer, question, answer, contexts)
            elif name == "rubrics_score":
                results[name] = await rubrics_score.score(scorer, question, answer, contexts)
            elif name == "answer_accuracy":
                results[name] = await answer_accuracy.score(scorer, question, answer, answer)
            elif name == "context_relevance":
                results[name] = await context_relevance.score(scorer, question, contexts)
            elif name == "response_groundedness":
                results[name] = await response_groundedness.score(scorer, answer, contexts)
        except Exception as e:
            print(f"  Warning: {name} failed: {e}")
            results[name] = None

    return results


def parse_contexts(raw: str) -> list[str]:
    return [c.strip() for c in raw.split(CONTEXT_SEPARATOR) if c.strip()]


async def process_csv(input_file: str, metrics: list[str] = None):
    input_path = INPUT_DIR / input_file
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return

    selected = metrics or ALL_METRICS
    scorers = setup_scorers(selected)
    rows = []

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    results = []
    for i, row in enumerate(rows):
        question = row["Question"]
        answer = row["Answer"]
        contexts = parse_contexts(row["Retrieve Context"])

        print(f"Evaluating row {i + 1}/{len(rows)}: {question[:50]}...")
        scores = await evaluate_row(scorers, question, answer, contexts)
        results.append({
            "Question": question,
            "Answer": answer,
            "Retrieve Context": row["Retrieve Context"],
            **scores,
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(input_file).stem
    output_path = OUTPUT_DIR / f"{stem}_results_{timestamp}.csv"

    fieldnames = ["Question", "Answer", "Retrieve Context"] + list(scorers.keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"Results saved to {output_path}")


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

_scorers = None


def get_scorers():
    global _scorers
    if _scorers is None:
        _scorers = setup_scorers()
    return _scorers


# --- Pydantic Models ---

class EvalRequest(BaseModel):
    question: str
    answer: str
    retrieve_context: list[str]
    metrics: list[str] | None = None


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


# --- API Routes ---

@app.post("/api/evaluate")
async def evaluate(req: EvalRequest):
    all_scorers = get_scorers()
    selected_scorers = all_scorers
    if req.metrics:
        selected_scorers = {k: v for k, v in all_scorers.items() if k in req.metrics}
    scores = await evaluate_row(selected_scorers, req.question, req.answer, req.retrieve_context)
    return {
        "question": req.question,
        "answer": req.answer,
        **scores,
    }


@app.get("/api/metrics")
async def list_metrics():
    return {"available_metrics": ALL_METRICS}


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


# Mount static files AFTER API routes
app.mount("/", StaticFiles(directory="public", html=True), name="static")


# --- CLI Entry Point ---

def run_api(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run("main:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ragas Evaluation Tool")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    csv_parser = subparsers.add_parser("csv", help="Evaluate from a CSV file in input/")
    csv_parser.add_argument("file", help="CSV filename in the input/ directory")
    csv_parser.add_argument(
        "--metrics",
        nargs="+",
        choices=ALL_METRICS,
        default=None,
        help="Specific metrics to run (default: all)",
    )

    api_parser = subparsers.add_parser("api", help="Run as a REST API server")
    api_parser.add_argument("--host", default="0.0.0.0")
    api_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.mode == "csv":
        asyncio.run(process_csv(args.file, getattr(args, "metrics", None)))
    elif args.mode == "api":
        run_api(args.host, args.port)
