"""Test sets, test questions, and annotation routes."""

import asyncio
import csv
import io
import json
import logging
import threading
from datetime import datetime

from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models import (
    TestGenRequest,
    TestSetCreate,
    QuestionAnnotation,
    BulkAnnotation,
    VALID_QUESTION_STATUSES,
    BULK_ACTION_TO_STATUS,
    MAX_CHUNKS_FOR_GENERATION,
    MAX_UPLOAD_QA_ROWS,
)
from config import KG_SUBPROCESS_TIMEOUT, MAX_UPLOAD_SIZE, KG_WORKER_URL, KG_WORKER_URLS, KG_THREAD_MODE
import db.init
from db.init import NOW_SQL, json_extract_sql

router = APIRouter(prefix="/api", tags=["testsets"])
logger = logging.getLogger(__name__)


def _safe(s: object) -> str:
    """Strip CRLF from user-controlled values before logging to prevent log injection."""
    return str(s).replace("\r", "\\r").replace("\n", "\\n")

# Track active generation threads by project_id to prevent duplicates
_active_generations: dict[int, int] = {}  # project_id -> test_set_id
_gen_lock = threading.Lock()


# --- Helpers ---


def _parse_test_question_row(row) -> dict:
    d = dict(row)
    rc = d.get("reference_contexts")
    d["reference_contexts"] = json.loads(rc) if rc else []
    uec = d.get("user_edited_contexts")
    d["user_edited_contexts"] = json.loads(uec) if uec else None
    mj = d.pop("metadata_json", None)
    d["metadata"] = json.loads(mj) if mj else None
    d.setdefault("category", "")
    return d


# --- Legacy endpoints ---


@router.post("/generate-testset")
async def generate_testset(req: TestGenRequest):
    from evaluation.metrics.testgen import (
        generate_testset_from_chunks,
        generate_testset_with_personas,
    )

    def _run_with_loop(fn):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return fn()
        finally:
            loop.close()

    if req.use_personas:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _run_with_loop(lambda: generate_testset_with_personas(
                chunks=req.chunks,
                testset_size=req.testset_size,
                num_personas=req.num_personas,
                custom_personas=req.custom_personas,
            )),
        )
        return result
    else:
        questions = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _run_with_loop(lambda: generate_testset_from_chunks(
                chunks=req.chunks,
                testset_size=req.testset_size,
                custom_personas=req.custom_personas,
            )),
        )
        return {"personas": [], "questions": questions}


@router.post("/upload-document")
async def upload_document(file: UploadFile = File(...)):
    chunks: list[bytes] = []
    total = 0
    async for chunk in file:
        total += len(chunk)
        if total > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="File exceeds 50MB size limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    text = content.decode("utf-8", errors="ignore")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return {
        "filename": file.filename,
        "chunks": paragraphs,
        "num_chunks": len(paragraphs),
    }


# --- Project test-set routes ---


@router.post("/projects/{project_id}/test-sets", status_code=201)
async def create_test_set(project_id: int, req: TestSetCreate):
    conn = db.init.get_db()

    # Validate project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Guard: prevent duplicate concurrent generations for the same project
    with _gen_lock:
        if project_id in _active_generations:
            raise HTTPException(
                status_code=409,
                detail="A test set is already being generated for this project",
            )

    # Determine how to source the chunk texts.
    #
    # Option A — use_kg_as_source=True:
    #   Load node page_content directly from the stored KG.  No chunk config
    #   required.  Always reuses the stored KG (no hash check, no rebuild).
    #
    # Option B — Graph RAG Documents only:
    #   No chunks needed; the Graph RAG path loads its own document KG.
    #
    # Option C — normal (default):
    #   Load chunks from the specified chunk_config_id.

    _GRAPH_RAG_ONLY_CATS = {"bridge", "comparative", "community"}

    chunks: list[str] = []

    if req.use_kg_as_source:
        from evaluation.metrics.testgen import load_full_kg_json as _load_full_kg_json
        import json as _json

        _kg_json = _load_full_kg_json(project_id, "chunks")
        if _kg_json is None:
            raise HTTPException(
                status_code=422,
                detail="No complete knowledge graph found for this project. Build a knowledge graph first.",
            )
        _nodes = _json.loads(_kg_json).get("nodes", [])
        chunks = [
            n.get("properties", {}).get("page_content", "")
            for n in _nodes
            if n.get("properties", {}).get("page_content", "").strip()
        ]
        if not chunks:
            raise HTTPException(
                status_code=422,
                detail="Knowledge graph exists but contains no node content.",
            )
    elif not (
        req.graph_rag_kg_source == "documents"
        and req.question_categories
        and set(req.question_categories.keys()) <= _GRAPH_RAG_ONLY_CATS
    ):
        if req.chunk_config_id is None:
            raise HTTPException(status_code=422, detail="chunk_config_id required unless using only Graph RAG (Documents) categories")

        cc = conn.execute(
            "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
            (req.chunk_config_id, project_id),
        ).fetchone()
        if cc is None:
            raise HTTPException(status_code=404, detail="Chunk config not found")

        chunk_rows = conn.execute(
            "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
            (req.chunk_config_id,),
        ).fetchall()
        if not chunk_rows:
            raise HTTPException(
                status_code=422,
                detail="No chunks found for this config. Generate chunks first.",
            )

        if MAX_CHUNKS_FOR_GENERATION > 0 and len(chunk_rows) > MAX_CHUNKS_FOR_GENERATION:
            raise HTTPException(
                status_code=422,
                detail=f"Too many chunks ({len(chunk_rows)}). Maximum {MAX_CHUNKS_FOR_GENERATION} supported for test generation.",
            )

        chunks = [r["content"] for r in chunk_rows]

    total_chunks = len(chunks)

    # Auto-generate name if not provided
    name = req.name or f"Test Set ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

    # Insert test_set row with 'generating' status
    generation_config = {
        "chunk_config_id": req.chunk_config_id,
        "testset_size": req.testset_size,
        "num_personas": req.num_personas,
        "custom_personas": req.custom_personas,
        "use_personas": req.use_personas,
        "query_distribution": req.query_distribution,
        "chunk_sample_size": req.chunk_sample_size,
        "num_workers": req.num_workers,
        "question_categories": req.question_categories,
        "total_chunks": total_chunks,
        "sampled_chunks": req.chunk_sample_size if req.chunk_sample_size > 0 else total_chunks,
    }
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json, status) VALUES (?, ?, ?, 'generating')",
        (project_id, name, json.dumps(generation_config)),
    )
    conn.commit()
    test_set_id = cursor.lastrowid

    # Register active generation
    with _gen_lock:
        _active_generations[project_id] = test_set_id

    # Spawn background thread for generation
    thread = threading.Thread(
        target=_run_generation,
        args=(project_id, test_set_id, chunks, req),
        daemon=True,
    )
    thread.start()

    return {
        "id": test_set_id,
        "name": name,
        "project_id": project_id,
        "status": "generating",
    }


def _run_generation(
    project_id: int,
    test_set_id: int,
    chunks: list[str],
    req: TestSetCreate,
) -> None:
    """Run test set generation in a background thread."""
    # Ragas internally calls asyncio.run() which needs a clean event loop.
    # Background threads inherit no loop, but the main FastAPI loop can
    # interfere on Python 3.12+.  Set a fresh loop explicitly.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    from evaluation.metrics.testgen import (
        generate_project_testset,
        register_cancel_flag,
        clear_cancel_flag,
        is_cancelled,
    )

    cancel_flag = register_cancel_flag(project_id)
    conn = db.init.get_thread_db()
    try:
        # When using KG as source with no explicit sample, set node_sample_size
        # to the total node count so the cached-KG path is always taken
        # (avoids a hash-miss rebuild when chunk_sample_size=0).
        node_sample_size = req.chunk_sample_size
        if req.use_kg_as_source and node_sample_size == 0:
            node_sample_size = len(chunks)

        result = generate_project_testset(
            chunks=chunks,
            testset_size=req.testset_size,
            use_personas=req.use_personas,
            num_personas=req.num_personas,
            custom_personas=req.custom_personas,
            query_distribution=req.query_distribution,
            num_workers=req.num_workers,
            question_categories=req.question_categories,
            project_id=project_id,
            graph_rag_kg_source=req.graph_rag_kg_source,
            node_sample_size=node_sample_size,
            fast_mode=req.fast_kg_mode,
        )

        # Insert questions
        questions = result.get("questions", [])
        personas = result.get("personas", [])
        persona_map = {p["name"]: p for p in personas} if personas else {}

        for q in questions:
            persona_name = q.get("persona") or (
                q.get("synthesizer_name") if not persona_map else None
            )
            category = q.get("category", "")
            conn.execute(
                """INSERT INTO test_questions
                   (test_set_id, question, reference_answer, reference_contexts, question_type, persona, category, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    test_set_id,
                    q.get("user_input", ""),
                    q.get("reference", ""),
                    json.dumps(q.get("reference_contexts", [])),
                    q.get("synthesizer_name", ""),
                    persona_name,
                    category,
                ),
            )

        if is_cancelled(project_id):
            conn.execute(
                "UPDATE test_sets SET status = 'cancelled' WHERE id = ?",
                (test_set_id,),
            )
            conn.commit()
            logger.info("Test set %d generation cancelled", test_set_id)
        else:
            conn.execute(
                "UPDATE test_sets SET status = 'completed' WHERE id = ?",
                (test_set_id,),
            )
            conn.commit()
            logger.info(
                "Test set %d generated successfully (%d questions)",
                test_set_id,
                len(questions),
            )

    except Exception as e:
        if is_cancelled(project_id):
            conn.execute(
                "UPDATE test_sets SET status = 'cancelled' WHERE id = ?",
                (test_set_id,),
            )
            logger.info("Test set %d generation cancelled (via exception)", test_set_id)
        else:
            err_msg = str(e)
            logger.exception(
                "Test set generation failed for test_set_id=%d", test_set_id
            )
            conn.execute(
                "UPDATE test_sets SET status = 'failed', error_message = ? WHERE id = ?",
                (err_msg[:2000], test_set_id),
            )
        conn.commit()

    finally:
        conn.close()
        clear_cancel_flag(project_id)
        with _gen_lock:
            _active_generations.pop(project_id, None)


def _parse_upload_file(content: bytes, filename: str) -> list[dict]:
    """Parse a CSV or JSON upload into a list of row dicts."""
    text = content.decode("utf-8", errors="ignore")

    if filename.lower().endswith(".json"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=422, detail=f"Invalid JSON: {e}")
        if not isinstance(parsed, list):
            raise HTTPException(
                status_code=422,
                detail="JSON must be an array of objects",
            )
        return parsed

    # CSV (including .csv, .tsv, or unknown extensions)
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


@router.post("/projects/{project_id}/test-sets/upload/preview")
async def preview_upload(project_id: int, file: UploadFile = File(...)):
    """Step 1: Upload a CSV/JSON file and preview columns + sample rows.

    Returns the column names and first 5 rows so the user can pick
    which column is the question and which is the reference answer.
    """
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="File too large (max 10MB)")

    filename = file.filename or "upload"
    rows = _parse_upload_file(content, filename)

    if not rows:
        raise HTTPException(status_code=422, detail="No rows found in file")
    if len(rows) > MAX_UPLOAD_QA_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many rows ({len(rows)}). Maximum {MAX_UPLOAD_QA_ROWS} allowed.",
        )

    columns = list(rows[0].keys())
    preview_rows = rows[:5]

    return {
        "filename": filename,
        "total_rows": len(rows),
        "columns": columns,
        "preview": preview_rows,
    }


class TestSetUploadConfirm(BaseModel):
    question_column: str
    answer_column: str
    contexts_column: str | None = None
    name: str | None = None


@router.post("/projects/{project_id}/test-sets/upload", status_code=201)
async def upload_test_set(
    project_id: int,
    file: UploadFile = File(...),
    question_column: str = Form(...),
    answer_column: str = Form(...),
    contexts_column: str | None = Form(None),
    reference_sql_column: str | None = Form(None),
    schema_contexts_column: str | None = Form(None),
    reference_data_column: str | None = Form(None),
    name: str | None = Form(None),
):
    """Step 2: Upload the same file again with chosen column mappings to create the test set.

    Form fields:
      - file: the CSV/JSON file
      - question_column: which column to use as the question
      - answer_column: which column to use as the reference answer
      - contexts_column: (optional) column for reference contexts
      - name: (optional) test set name
    """
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="File too large (max 10MB)")

    filename = file.filename or "upload"
    rows = _parse_upload_file(content, filename)

    if not rows:
        raise HTTPException(status_code=422, detail="No rows found in file")
    if len(rows) > MAX_UPLOAD_QA_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many rows ({len(rows)}). Maximum {MAX_UPLOAD_QA_ROWS} allowed.",
        )

    # Validate that chosen columns exist
    columns = set(rows[0].keys())
    if question_column not in columns:
        raise HTTPException(
            status_code=422,
            detail=f"Column '{question_column}' not found. Available: {sorted(columns)}",
        )
    if answer_column not in columns:
        raise HTTPException(
            status_code=422,
            detail=f"Column '{answer_column}' not found. Available: {sorted(columns)}",
        )
    if contexts_column and contexts_column not in columns:
        raise HTTPException(
            status_code=422,
            detail=f"Column '{contexts_column}' not found. Available: {sorted(columns)}",
        )
    for col_name, col_label in [
        (reference_sql_column, "reference_sql_column"),
        (schema_contexts_column, "schema_contexts_column"),
        (reference_data_column, "reference_data_column"),
    ]:
        if col_name and col_name not in columns:
            raise HTTPException(
                status_code=422,
                detail=f"Column '{col_name}' ({col_label}) not found. Available: {sorted(columns)}",
            )

    # Validate rows have non-empty values in chosen columns
    for i, row in enumerate(rows):
        if not (row.get(question_column) or "").strip():
            raise HTTPException(
                status_code=422,
                detail=f"Row {i + 1}: '{question_column}' is empty",
            )
        if not (row.get(answer_column) or "").strip():
            raise HTTPException(
                status_code=422,
                detail=f"Row {i + 1}: '{answer_column}' is empty",
            )

    # Create test_set
    set_name = name or f"Uploaded ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    generation_config = {
        "source": "upload",
        "filename": filename,
        "row_count": len(rows),
        "column_mapping": {
            "question": question_column,
            "answer": answer_column,
            "contexts": contexts_column,
            "reference_sql": reference_sql_column,
            "schema_contexts": schema_contexts_column,
            "reference_data": reference_data_column,
        },
    }
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
        (project_id, set_name, json.dumps(generation_config)),
    )
    conn.commit()
    test_set_id = cursor.lastrowid

    # Build domain column mapping: metadata_key -> csv_column_name
    _domain_col_map: dict[str, str] = {}
    if reference_sql_column:
        _domain_col_map["reference_sql"] = reference_sql_column
    if schema_contexts_column:
        _domain_col_map["schema_contexts"] = schema_contexts_column
    if reference_data_column:
        _domain_col_map["reference_data"] = reference_data_column

    # Validate domain-specific column values upfront
    for i, row in enumerate(rows):
        for meta_key, col_name in _domain_col_map.items():
            val = row.get(col_name, "")
            if not val or not str(val).strip():
                continue
            if meta_key == "reference_sql":
                upper = str(val).strip().upper()
                sql_keywords = {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "WITH"}
                if not any(kw in upper for kw in sql_keywords):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {i + 1}, column '{col_name}': does not appear to be a valid SQL statement.",
                    )
            elif meta_key == "schema_contexts":
                stripped = str(val).strip()
                if stripped.startswith("[") or stripped.startswith("{"):
                    try:
                        parsed = json.loads(stripped)
                        if not isinstance(parsed, list):
                            raise HTTPException(
                                status_code=422,
                                detail=f"Row {i + 1}, column '{col_name}': JSON must be an array of strings, got {type(parsed).__name__}.",
                            )
                    except json.JSONDecodeError as e:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Row {i + 1}, column '{col_name}': invalid JSON — {e}",
                        )

    # Insert questions
    inserted = []
    for row in rows:
        ref_ctx: list = []
        if contexts_column:
            raw = row.get(contexts_column, "")
            if isinstance(raw, list):
                ref_ctx = raw
            elif isinstance(raw, str) and raw.strip():
                try:
                    ref_ctx = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    ref_ctx = [raw]

        # Build metadata from user-selected domain columns
        metadata: dict = {}
        for meta_key, col_name in _domain_col_map.items():
            val = row.get(col_name, "")
            if not val or not str(val).strip():
                continue
            if meta_key == "schema_contexts":
                try:
                    parsed = json.loads(val)
                    metadata[meta_key] = parsed if isinstance(parsed, list) else [str(parsed)]
                except (json.JSONDecodeError, TypeError):
                    metadata[meta_key] = [str(val).strip()]
            else:
                metadata[meta_key] = str(val).strip()
        metadata_json_val = json.dumps(metadata) if metadata else None

        conn.execute(
            """INSERT INTO test_questions
               (test_set_id, question, reference_answer, reference_contexts, question_type, persona, metadata_json, status)
               VALUES (?, ?, ?, ?, 'uploaded', '', ?, 'pending')""",
            (
                test_set_id,
                row[question_column].strip(),
                row[answer_column].strip(),
                json.dumps(ref_ctx),
                metadata_json_val,
            ),
        )
        inserted.append(
            {
                "question": row[question_column].strip(),
                "reference_answer": row[answer_column].strip(),
                "reference_contexts": ref_ctx,
                "question_type": "uploaded",
                "status": "pending",
                "metadata": metadata or None,
            }
        )
    conn.commit()

    return {
        "id": test_set_id,
        "name": set_name,
        "project_id": project_id,
        "question_count": len(inserted),
        "questions": inserted,
    }


@router.post("/projects/{project_id}/test-sets/{test_set_id}/cancel")
async def cancel_test_set_generation(project_id: int, test_set_id: int):
    """Cancel an in-progress test set generation."""
    from evaluation.metrics.testgen import cancel_generation

    conn = db.init.get_db()
    row = conn.execute(
        "SELECT status FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Test set not found")
    if row["status"] != "generating":
        raise HTTPException(
            status_code=409,
            detail=f"Test set is not generating (current status: {row['status']})",
        )

    cancel_generation(project_id)
    return {"status": "cancelling", "test_set_id": test_set_id}


@router.get("/projects/{project_id}/test-sets/generation-progress")
async def generation_progress(project_id: int):
    from evaluation.metrics.testgen import get_progress

    progress = get_progress(project_id, kg_source="testset")

    # Check DB for completed/failed/cancelled status when no in-memory progress
    # (generation finished and cleared progress, or server restarted)
    if progress is None:
        conn = db.init.get_db()
        row = conn.execute(
            "SELECT id, status, error_message FROM test_sets "
            "WHERE project_id = ? AND status IN ('generating', 'completed', 'failed', 'cancelled') "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if row is None:
            return {"active": False}
        if row["status"] == "generating":
            # Generation thread may have died (e.g. server restart)
            # Mark as failed if no active thread
            with _gen_lock:
                if project_id not in _active_generations:
                    conn.execute(
                        "UPDATE test_sets SET status = 'failed', error_message = 'Generation interrupted (server restart)' WHERE id = ?",
                        (row["id"],),
                    )
                    conn.commit()
                    return {
                        "active": False,
                        "status": "failed",
                        "test_set_id": row["id"],
                        "error_message": "Generation interrupted (server restart)",
                    }
            return {"active": True, "status": "generating", "test_set_id": row["id"]}
        if row["status"] == "completed":
            return {"active": False, "status": "completed", "test_set_id": row["id"]}
        if row["status"] == "cancelled":
            return {"active": False, "status": "cancelled", "test_set_id": row["id"]}
        if row["status"] == "failed":
            return {
                "active": False,
                "status": "failed",
                "test_set_id": row["id"],
                "error_message": row["error_message"],
            }
        return {"active": False}

    return {"active": True, **progress}


@router.get("/projects/{project_id}/test-sets")
async def list_test_sets(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = conn.execute(
        f"""SELECT ts.id, ts.name, ts.generation_config_json, ts.created_at,
                  ts.status AS generation_status, ts.error_message,
                  COUNT(tq.id) AS total_questions,
                  SUM(CASE WHEN tq.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                  SUM(CASE WHEN tq.status = 'approved' THEN 1 ELSE 0 END) AS approved_count,
                  SUM(CASE WHEN tq.status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count
           FROM test_sets ts
           LEFT JOIN test_questions tq ON tq.test_set_id = ts.id
           WHERE ts.project_id = ? AND ts.status != 'generating'
                 AND COALESCE({json_extract_sql('ts.generation_config_json', 'source')}, '') != 'csv_auto'
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


@router.get("/projects/{project_id}/test-sets/{test_set_id}/questions")
async def list_test_questions(
    project_id: int, test_set_id: int, status: str | None = None
):
    conn = db.init.get_db()

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


@router.delete(
    "/projects/{project_id}/test-sets/{test_set_id}", status_code=204
)
async def delete_test_set(project_id: int, test_set_id: int):
    conn = db.init.get_db()

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


@router.patch(
    "/projects/{project_id}/test-sets/{test_set_id}/questions/{question_id}"
)
async def annotate_question(
    project_id: int,
    test_set_id: int,
    question_id: int,
    req: QuestionAnnotation,
):
    conn = db.init.get_db()

    # Validate project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
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
    edited_ctx_json = json.dumps(req.user_edited_contexts) if req.user_edited_contexts is not None else None
    metadata_json = json.dumps(req.metadata) if req.metadata is not None else None
    conn.execute(
        f"""UPDATE test_questions
           SET status = ?, user_edited_answer = ?, user_edited_contexts = ?, user_notes = ?,
               metadata_json = COALESCE(?, metadata_json),
               reviewed_at = {NOW_SQL}
           WHERE id = ?""",
        (req.status, req.user_edited_answer, edited_ctx_json, req.user_notes, metadata_json, question_id),
    )
    conn.commit()

    # Re-read from DB to return truth
    updated = conn.execute(
        "SELECT * FROM test_questions WHERE id = ?", (question_id,)
    ).fetchone()
    return _parse_test_question_row(updated)


@router.post(
    "/projects/{project_id}/test-sets/{test_set_id}/questions/bulk"
)
async def bulk_annotate_questions(
    project_id: int, test_set_id: int, req: BulkAnnotation
):
    conn = db.init.get_db()

    # Validate project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
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
    updated_count = 0

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
        invalid_ids = [
            qid for qid in req.question_ids if qid not in valid_ids
        ]
        if invalid_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Question IDs not found in this test set: {invalid_ids}",
            )

        # Update specified questions
        cursor = conn.execute(
            f"UPDATE test_questions SET status = ?, reviewed_at = {NOW_SQL} WHERE id IN ({placeholders}) AND test_set_id = ?",
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
            f"UPDATE test_questions SET status = ?, reviewed_at = {NOW_SQL} WHERE test_set_id = ? AND status = 'pending'",
            (target_status, test_set_id),
        )
        conn.commit()
        updated_count = cursor.rowcount

    return {"updated_count": updated_count}


@router.get("/projects/{project_id}/test-sets/{test_set_id}/summary")
async def test_set_summary(project_id: int, test_set_id: int):
    conn = db.init.get_db()

    # Validate project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
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
    completion_pct = (
        round(((counts["approved"] + counts["edited"]) / total) * 100, 1)
        if total > 0
        else 0.0
    )

    return {
        "test_set_id": test_set_id,
        "total": total,
        **counts,
        "completion_pct": completion_pct,
    }


# --- Knowledge Graph Helpers ---


def _kg_node_to_dict(node) -> dict:
    """Convert a Ragas KG node to a serializable dict for the API."""
    props = node.properties if hasattr(node, "properties") else {}
    headlines = props.get("headlines")
    if isinstance(headlines, list) and headlines:
        label = headlines[0][:80]
    elif isinstance(headlines, str) and headlines:
        label = headlines[:80]
    else:
        content = props.get("page_content", "")
        if not content:
            for v in props.values():
                if isinstance(v, str) and len(v) > 10:
                    content = v
                    break
        label = (content[:80] + "\u2026") if len(content) > 80 else content

    keyphrases = props.get("keyphrases", [])
    if isinstance(keyphrases, str):
        keyphrases = [k.strip() for k in keyphrases.split(",") if k.strip()]

    return {
        "id": str(node.id),
        "type": node.type.value if hasattr(node.type, "value") else str(node.type),
        "label": label,
        "keyphrases": keyphrases[:15],
    }


def _kg_edge_score(rel) -> float:
    """Extract the best available score from a KG relationship."""
    props = rel.properties if hasattr(rel, "properties") else {}
    for key in ("keyphrases_overlap_score", "summary_similarity", "entities_entity_overlap", "overlap_score", "score"):
        val = props.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.5


def _filter_kg_edges(
    relationships,
    max_per_node: int = 8,
    min_score: float = 0.0,
) -> list[dict]:
    """Build a filtered edge list from KG relationships, capping per-node degree."""
    all_edges = []
    for rel in relationships:
        score = _kg_edge_score(rel)
        if score < min_score:
            continue
        all_edges.append({
            "source": str(rel.source.id),
            "target": str(rel.target.id),
            "type": rel.type or "overlap",
            "score": round(score, 3),
        })

    all_edges.sort(key=lambda e: e["score"], reverse=True)
    node_edge_count: dict[str, int] = {}
    edges = []
    for edge in all_edges:
        src_count = node_edge_count.get(edge["source"], 0)
        tgt_count = node_edge_count.get(edge["target"], 0)
        if src_count >= max_per_node and tgt_count >= max_per_node:
            continue
        edges.append(edge)
        node_edge_count[edge["source"]] = src_count + 1
        node_edge_count[edge["target"]] = tgt_count + 1
    return edges


# --- Knowledge Graph Cache Routes ---


@router.get("/projects/{project_id}/knowledge-graph")
async def get_knowledge_graph_info(project_id: int, kg_source: str = "chunks"):
    """Return metadata about the cached knowledge graph for a project.

    Includes a ``chunks_stale`` flag indicating whether the current source content
    differs from what was used to build the cached KG.
    """
    from evaluation.metrics.testgen import get_kg_info, _chunks_hash

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    info = get_kg_info(project_id, kg_source=kg_source)
    if info is None:
        return {"exists": False, "kg_source": kg_source}

    # Check staleness depending on source type
    chunks_stale = False
    stored_hash = info.get("chunks_hash")
    if stored_hash:
        if kg_source == "documents":
            doc_rows = conn.execute(
                "SELECT content FROM documents WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            if doc_rows:
                current_hash = _chunks_hash([r["content"] for r in doc_rows])
                chunks_stale = current_hash != stored_hash
        else:
            chunk_config_id = info.get("chunk_config_id")
            if chunk_config_id:
                chunk_rows = conn.execute(
                    "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
                    (chunk_config_id,),
                ).fetchall()
                if chunk_rows:
                    current_hash = _chunks_hash([r["content"] for r in chunk_rows])
                    chunks_stale = current_hash != stored_hash

    return {"exists": True, "chunks_stale": chunks_stale, "kg_source": kg_source, **info}


@router.delete("/projects/{project_id}/knowledge-graph", status_code=204)
async def delete_knowledge_graph(project_id: int, kg_source: str = "chunks"):
    """Delete the cached knowledge graph for a project."""
    from evaluation.metrics.testgen import delete_kg_from_db

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    deleted = delete_kg_from_db(project_id, kg_source=kg_source)
    if not deleted:
        raise HTTPException(
            status_code=404, detail="No knowledge graph found for this project"
        )
    return None


# Track active KG builds to prevent duplicates — keyed by (project_id, kg_source)
_active_kg_builds: dict[tuple[int, str], bool] = {}
_kg_lock = threading.Lock()

# Track which worker URL accepted each project's KG build for correct progress routing.
# Lost on main-app restart — progress endpoint falls back to trying all workers.
_project_worker: dict[tuple[int, str], str] = {}

# Prepended to every KG subprocess script to suppress BrokenPipeError noise.
# When the parent closes stdout after reading KG_BUILD_OK, Python's shutdown
# would normally print "Exception ignored while flushing sys.stdout: BrokenPipeError".
# Setting SIGPIPE to SIG_DFL makes the process exit silently on a broken pipe instead.
_SUBPROCESS_PREAMBLE = (
    "import signal as _sig; "
    "_sig.signal(_sig.SIGPIPE, _sig.SIG_DFL) "
    "if hasattr(_sig, 'SIGPIPE') else None; "
)


def _run_kg_in_thread(
    project_id: int,
    kg_source: str,
    chunk_config_id: int | None,
    overlap_max_nodes: int | None,
    fast_mode: bool,
) -> None:
    """Run KG build directly in a thread sharing the main process's imports.

    Unlike the subprocess approach, this reuses the already-imported ragas
    library so the container's memory is not doubled by a fresh Python process.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("KG thread build starting: project=%d source=%s", project_id, kg_source)
        from evaluation.metrics.testgen import set_progress, clear_progress

        set_progress(project_id, {"stage": "building_knowledge_graph", "kg_building": True}, kg_source=kg_source)

        if kg_source == "documents":
            from evaluation.metrics.testgen import build_kg_standalone_from_documents
            build_kg_standalone_from_documents(project_id=project_id, overlap_max_nodes=overlap_max_nodes)
        else:
            from evaluation.metrics.testgen import build_kg_standalone
            build_kg_standalone(
                chunk_config_id=chunk_config_id,
                project_id=project_id,
                overlap_max_nodes=overlap_max_nodes,
                fast_mode=fast_mode,
            )
        logger.info("KG thread build completed: project=%d source=%s", project_id, kg_source)
    except Exception as exc:
        logger.exception("KG thread build failed: project=%d: %s", project_id, exc)
    finally:
        from evaluation.metrics.testgen import clear_progress
        clear_progress(project_id, kg_source=kg_source)
        loop.close()
        with _kg_lock:
            _active_kg_builds.pop((project_id, kg_source), None)


def _run_kg_subprocess(
    project_id: int,
    script: str,
    args: list[str],
    success_marker: str,
    initial_stage: str,
    kg_source: str = "chunks",
) -> None:
    """Run a KG operation in a subprocess with progress tracking and cleanup.

    Common pattern for build, rebuild-links, and incremental update endpoints.
    Progress lines emitted by the subprocess (JSON with _progress=True) are
    forwarded to the parent process's in-memory progress store so the frontend
    polling endpoint can reflect real step-by-step status.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    project_dir = str(Path(__file__).resolve().parents[2])

    try:
        logger.info("KG subprocess thread started: project=%d source=%s", project_id, kg_source)
        from evaluation.metrics.testgen import set_progress, clear_progress
        set_progress(project_id, {
            "stage": initial_stage,
            "kg_building": True,
        }, kg_source=kg_source)

        env = {**__import__("os").environ, "KG_PROGRESS_PIPE": "1"}
        proc = subprocess.Popen(
            [sys.executable, "-c", script, project_dir, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        # Kill the subprocess if it runs too long
        kill_timer = threading.Timer(KG_SUBPROCESS_TIMEOUT, proc.kill)
        kill_timer.start()

        stdout_lines: list[str] = []
        success = False
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                stdout_lines.append(line)
                if success_marker in line:
                    success = True
                # Forward structured progress from subprocess to parent process
                try:
                    data = json.loads(line)
                    if data.get("_progress"):
                        proj_id = data.pop("project_id", project_id)
                        src = data.pop("kg_source", kg_source)
                        data.pop("_progress", None)
                        set_progress(proj_id, data, kg_source=src)
                    else:
                        print(f"[KG-SUB] {line}", flush=True)
                except (json.JSONDecodeError, AttributeError):
                    print(f"[KG-SUB] {line}", flush=True)
        finally:
            kill_timer.cancel()
            proc.wait()

        stderr_out = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
        if stderr_out:
            logger.error("KG subprocess stderr: %s", stderr_out[-2000:])

        if proc.returncode != 0 or not success:
            logger.error(
                "KG subprocess failed (rc=%d, marker=%s): %s",
                proc.returncode,
                success_marker,
                "\n".join(stdout_lines[-20:]) or "no output",
            )
            raise RuntimeError(f"KG operation failed ({success_marker})")

        logger.info("KG operation '%s' completed for project %d", success_marker, project_id)
    except Exception as _exc:
        print(f"[KG] EXCEPTION project={project_id}: {_exc}", flush=True)
        logger.exception("KG operation failed for project %d", project_id)
    finally:
        from evaluation.metrics.testgen import clear_progress
        clear_progress(project_id, kg_source=kg_source)
        with _kg_lock:
            _active_kg_builds.pop((project_id, kg_source), None)


class BuildKGRequest(BaseModel):
    chunk_config_id: int | None = None
    overlap_max_nodes: int | None = 500
    kg_source: Literal["chunks", "documents"] = "chunks"
    fast_mode: bool = False


def _make_doc_kg_script(overlap_max_nodes: int | None) -> str:
    overlap_arg = f", overlap_max_nodes={overlap_max_nodes}" if overlap_max_nodes is not None else ", overlap_max_nodes=None"
    return (
        _SUBPROCESS_PREAMBLE +
        "import sys, os; os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1]); "
        "from evaluation.metrics.testgen import build_kg_standalone_from_documents; "
        f"build_kg_standalone_from_documents(project_id=int(sys.argv[2]){overlap_arg}); "
        "print('KG_BUILD_OK')"
    )


def _make_chunk_kg_script(chunk_config_id: int, overlap_max_nodes: int | None, fast_mode: bool) -> str:
    overlap_arg = f", overlap_max_nodes={overlap_max_nodes}" if overlap_max_nodes is not None else ", overlap_max_nodes=None"
    fast_arg = f", fast_mode={fast_mode}" if fast_mode else ""
    return (
        _SUBPROCESS_PREAMBLE +
        "import sys, os; os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1]); "
        "from evaluation.metrics.testgen import build_kg_standalone; "
        f"build_kg_standalone(chunk_config_id=int(sys.argv[2]), project_id=int(sys.argv[3]){overlap_arg}{fast_arg}); "
        "print('KG_BUILD_OK')"
    )


@router.post("/projects/{project_id}/build-knowledge-graph")
async def build_knowledge_graph_endpoint(project_id: int, req: BuildKGRequest):
    """Start building a knowledge graph in the background."""
    logger.info("KG generate clicked: project=%d source=%s fast=%s", project_id, _safe(req.kg_source), req.fast_mode)

    # Offload to worker service(s) if configured
    if KG_WORKER_URLS:
        import httpx
        payload = {
            "project_id": project_id,
            "chunk_config_id": req.chunk_config_id,
            "kg_source": req.kg_source,
            "overlap_max_nodes": req.overlap_max_nodes,
            "fast_mode": req.fast_mode,
        }
        key = (project_id, req.kg_source)
        async with httpx.AsyncClient(timeout=10) as client:
            for worker_url in KG_WORKER_URLS:
                try:
                    resp = await client.post(f"{worker_url}/build-kg", json=payload)
                    if resp.status_code == 202:
                        _project_worker[key] = worker_url
                        logger.info("KG build delegated to worker: %s", worker_url)
                        return resp.json()
                    if resp.status_code == 409:
                        raise HTTPException(status_code=409, detail=resp.json().get("detail", "Build already in progress"))
                    # 503 = worker at capacity, try next
                    logger.debug("Worker %s at capacity, trying next", worker_url)
                except HTTPException:
                    raise
                except Exception as e:
                    logger.warning("Worker %s unreachable: %s", worker_url, e)
        raise HTTPException(status_code=503, detail="All KG workers busy or unreachable — try again shortly")

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if req.kg_source == "documents":
        # Document-level KG — no chunk_config_id needed
        doc_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE project_id = ?", (project_id,)
        ).fetchone()["cnt"]
        if doc_count == 0:
            raise HTTPException(status_code=422, detail="No documents found for this project")

        with _kg_lock:
            if _active_kg_builds.get((project_id, "documents")):
                raise HTTPException(
                    status_code=409,
                    detail="Knowledge graph build already in progress",
                )
            _active_kg_builds[(project_id, "documents")] = True

        _kg_target = _run_kg_in_thread if KG_THREAD_MODE else _run_kg_subprocess
        _kg_args = (
            (project_id, "documents", None, req.overlap_max_nodes, False)
            if KG_THREAD_MODE else
            (project_id, _make_doc_kg_script(req.overlap_max_nodes), [str(project_id)], "KG_BUILD_OK", "building_knowledge_graph", "documents")
        )
        threading.Thread(target=_kg_target, args=_kg_args, daemon=True).start()
    else:
        # Chunk-based KG (default)
        if req.chunk_config_id is None:
            raise HTTPException(status_code=422, detail="chunk_config_id required for chunks source")
        cc = conn.execute(
            "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
            (req.chunk_config_id, project_id),
        ).fetchone()
        if cc is None:
            raise HTTPException(status_code=404, detail="Chunk config not found")

        with _kg_lock:
            if _active_kg_builds.get((project_id, "chunks")):
                raise HTTPException(
                    status_code=409,
                    detail="Knowledge graph build already in progress",
                )
            _active_kg_builds[(project_id, "chunks")] = True

        _kg_target = _run_kg_in_thread if KG_THREAD_MODE else _run_kg_subprocess
        _kg_args = (
            (project_id, "chunks", req.chunk_config_id, req.overlap_max_nodes, req.fast_mode)
            if KG_THREAD_MODE else
            (project_id, _make_chunk_kg_script(req.chunk_config_id, req.overlap_max_nodes, req.fast_mode), [str(req.chunk_config_id), str(project_id)], "KG_BUILD_OK", "building_knowledge_graph", "chunks")
        )
        threading.Thread(target=_kg_target, args=_kg_args, daemon=True).start()

    return {"status": "building", "project_id": project_id, "kg_source": req.kg_source}


@router.get("/projects/{project_id}/knowledge-graph/progress")
async def kg_build_progress(project_id: int, kg_source: Literal["chunks", "documents"] = "chunks"):
    """Poll knowledge graph build progress."""
    from evaluation.metrics.testgen import get_progress, get_kg_info

    # When using worker(s), proxy progress — try the known worker first, then others
    if KG_WORKER_URLS:
        import httpx
        key = (project_id, kg_source)
        known = _project_worker.get(key)
        candidates = ([known] + [u for u in KG_WORKER_URLS if u != known]) if known else KG_WORKER_URLS
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                for worker_url in candidates:
                    try:
                        resp = await client.get(
                            f"{worker_url}/progress/{int(project_id)}",
                            params={"kg_source": kg_source},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get("active") or data.get("status"):
                                return data
                    except Exception:
                        continue
        except Exception:
            pass  # fall through to local DB check on all workers unreachable

    # Check if a build thread is actively running
    with _kg_lock:
        thread_active = _active_kg_builds.get((project_id, kg_source)) is not None

    # Check in-memory progress (set by main process wrapper)
    progress = get_progress(project_id, kg_source=kg_source)
    if thread_active:
        if progress and progress.get("kg_building"):
            return {"active": True, **progress}
        return {"active": True, "stage": "building_knowledge_graph"}

    # No active thread registered in this process (server restart or build never
    # started).  We cannot trust the heartbeat here — the heartbeat may be fresh
    # because the previous server process wrote it just before dying.  Since we
    # know no thread is running in THIS process, the build is definitively not
    # active, regardless of heartbeat age.
    info = get_kg_info(project_id, kg_source=kg_source)
    if info:
        if info.get("is_complete"):
            return {"active": False, "status": "completed", **info}
        # Partial KG with no active thread = interrupted (server restart / crash).
        return {
            "active": False,
            "status": "partial",
            "stale": True,
            **info,
        }

    return {"active": False}


@router.post("/projects/{project_id}/knowledge-graph/reset")
async def kg_reset_stale(project_id: int, kg_source: str = "chunks"):
    """Delete a partial/stale KG checkpoint so a fresh build can start."""
    from evaluation.metrics.testgen import get_kg_info, delete_kg_from_db, clear_progress

    with _kg_lock:
        if _active_kg_builds.get((project_id, kg_source)):
            raise HTTPException(400, "A build is currently running — cannot reset")

    info = get_kg_info(project_id, kg_source=kg_source)
    if not info:
        return {"deleted": False, "reason": "no KG found"}

    deleted = delete_kg_from_db(project_id, kg_source=kg_source)
    clear_progress(project_id, kg_source=kg_source)
    return {"deleted": deleted, "was_complete": info.get("is_complete", False)}


class RebuildLinksRequest(BaseModel):
    overlap_max_nodes: int | None = 500


@router.post("/projects/{project_id}/knowledge-graph/rebuild-links")
async def rebuild_kg_links_endpoint(project_id: int, req: RebuildLinksRequest):
    """Rebuild only the overlap/link step of a KG with new parameters."""
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    with _kg_lock:
        if _active_kg_builds.get((project_id, "chunks")):
            raise HTTPException(
                status_code=409,
                detail="Knowledge graph build already in progress",
            )
        _active_kg_builds[(project_id, "chunks")] = True

    overlap_arg = f", overlap_max_nodes={req.overlap_max_nodes}" if req.overlap_max_nodes is not None else ", overlap_max_nodes=None"
    script = (
        _SUBPROCESS_PREAMBLE +
        "import sys, os; "
        "os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1]); "
        "from evaluation.metrics.testgen import rebuild_kg_links; "
        "result = rebuild_kg_links("
        "project_id=int(sys.argv[2])"
        f"{overlap_arg}); "
        "print('REBUILD_OK')"
    )

    thread = threading.Thread(
        target=_run_kg_subprocess,
        args=(project_id, script, [str(project_id)], "REBUILD_OK", "kg_building_overlap", "chunks"),
        daemon=True,
    )
    thread.start()

    return {"status": "rebuilding", "project_id": project_id}


class UpdateKGRequest(BaseModel):
    chunk_config_id: int
    overlap_max_nodes: int | None = 500


@router.post("/projects/{project_id}/knowledge-graph/update")
async def update_knowledge_graph_endpoint(project_id: int, req: UpdateKGRequest):
    """Incrementally update a KG when documents are added or removed.

    Compares current chunks against the cached KG and applies only the
    necessary changes (add new nodes, remove deleted nodes, rebuild links).
    Much faster than a full rebuild when only a few documents changed.
    """
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    cc = conn.execute(
        "SELECT id FROM chunk_configs WHERE id = ? AND project_id = ?",
        (req.chunk_config_id, project_id),
    ).fetchone()
    if cc is None:
        raise HTTPException(status_code=404, detail="Chunk config not found")

    # Must have an existing KG to update incrementally
    existing = conn.execute(
        "SELECT id FROM knowledge_graphs WHERE project_id = ?", (project_id,)
    ).fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="No existing knowledge graph — use full build instead",
        )

    with _kg_lock:
        if _active_kg_builds.get((project_id, "chunks")):
            raise HTTPException(
                status_code=409,
                detail="Knowledge graph build already in progress",
            )
        _active_kg_builds[(project_id, "chunks")] = True

    overlap_arg = (
        f", overlap_max_nodes={req.overlap_max_nodes}"
        if req.overlap_max_nodes is not None
        else ", overlap_max_nodes=None"
    )
    script = (
        _SUBPROCESS_PREAMBLE +
        "import sys, os; "
        "os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1]); "
        "from evaluation.metrics.testgen import incremental_update_kg; "
        "result = incremental_update_kg("
        "project_id=int(sys.argv[2]), "
        "chunk_config_id=int(sys.argv[3])"
        f"{overlap_arg}); "
        "print('KG_UPDATE_OK')"
    )

    thread = threading.Thread(
        target=_run_kg_subprocess,
        args=(project_id, script, [str(project_id), str(req.chunk_config_id)], "KG_UPDATE_OK", "kg_diffing_chunks", "chunks"),
        daemon=True,
    )
    thread.start()

    return {"status": "updating", "project_id": project_id}


@router.get("/projects/{project_id}/knowledge-graph/data")
async def get_knowledge_graph_data(project_id: int):
    """Return the full KG graph data for visualization (nodes + edges)."""
    import tempfile
    from pathlib import Path as _Path

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = conn.execute(
        "SELECT kg_json, is_complete FROM knowledge_graphs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No knowledge graph found")

    # Parse KG JSON via Ragas loader
    from ragas.testset.graph import KnowledgeGraph

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(row["kg_json"])
        tmp_path = f.name
    try:
        kg = KnowledgeGraph.load(tmp_path)
    finally:
        _Path(tmp_path).unlink(missing_ok=True)

    nodes = [_kg_node_to_dict(node) for node in kg.nodes]
    edges = _filter_kg_edges(kg.relationships)

    return {
        "nodes": nodes,
        "edges": edges,
        "is_complete": bool(row["is_complete"]),
    }


@router.get("/projects/{project_id}/knowledge-graph/stream")
async def stream_knowledge_graph_data(project_id: int):
    """Stream KG graph data via SSE for progressive loading."""
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = conn.execute(
        "SELECT kg_json, is_complete FROM knowledge_graphs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No knowledge graph found")

    is_complete = bool(row["is_complete"])
    kg_json_text = row["kg_json"]

    async def _stream():
        from ragas.testset.graph import KnowledgeGraph

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", errors="replace") as f:
            f.write(kg_json_text)
            tmp_path = f.name
        try:
            kg = KnowledgeGraph.load(tmp_path)
        finally:
            _Path(tmp_path).unlink(missing_ok=True)

        # Stream nodes in batches of 50
        node_batch: list[dict] = []
        total_nodes = len(kg.nodes)
        total_edges = len(kg.relationships)

        # Send metadata first
        yield f"data: {_json.dumps({'type': 'meta', 'total_nodes': total_nodes, 'total_edges': total_edges, 'is_complete': is_complete})}\n\n"

        for node in kg.nodes:
            node_batch.append(_kg_node_to_dict(node))

            if len(node_batch) >= 50:
                yield f"data: {_json.dumps({'type': 'nodes', 'batch': node_batch})}\n\n"
                node_batch = []

        if node_batch:
            yield f"data: {_json.dumps({'type': 'nodes', 'batch': node_batch})}\n\n"

        filtered_edges = _filter_kg_edges(kg.relationships, min_score=0.5)

        # Stream filtered edges in batches of 100
        edge_batch: list[dict] = []
        for edge in filtered_edges:
            edge_batch.append(edge)

            if len(edge_batch) >= 100:
                yield f"data: {_json.dumps({'type': 'edges', 'batch': edge_batch})}\n\n"
                edge_batch = []

        if edge_batch:
            yield f"data: {_json.dumps({'type': 'edges', 'batch': edge_batch})}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/knowledge-graphs")
async def list_all_knowledge_graphs():
    """List all saved knowledge graphs across projects."""
    from evaluation.metrics.testgen import _chunks_hash

    conn = db.init.get_db()
    rows = conn.execute(
        "SELECT kg.id, kg.project_id, p.name AS project_name, "
        "kg.num_nodes, kg.num_chunks, kg.is_complete, kg.chunks_hash, "
        "kg.completed_steps, kg.total_steps, kg.chunk_config_id, kg.kg_source, kg.created_at "
        "FROM knowledge_graphs kg "
        "JOIN projects p ON p.id = kg.project_id "
        "ORDER BY kg.created_at DESC"
    ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        # Normalize old KGs to the new 11-step pipeline
        d["total_steps"] = 11
        if d["completed_steps"] < 11:
            d["is_complete"] = False
        # Check if chunks have changed since build
        chunks_stale = False
        if d.get("chunk_config_id") and d.get("chunks_hash"):
            chunk_rows = conn.execute(
                "SELECT content FROM chunks WHERE chunk_config_id = ? ORDER BY id",
                (d["chunk_config_id"],),
            ).fetchall()
            if chunk_rows:
                current_hash = _chunks_hash([r["content"] for r in chunk_rows])
                chunks_stale = current_hash != d["chunks_hash"]
        d["chunks_stale"] = chunks_stale
        d.pop("chunks_hash", None)  # don't expose internal hash
        result.append(d)
    return result
