"""Test sets, test questions, and annotation routes."""

import asyncio
import csv
import io
import json
import logging
import random
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
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
import db.init

router = APIRouter(prefix="/api", tags=["testsets"])
logger = logging.getLogger(__name__)


# --- Helpers ---


def _parse_test_question_row(row) -> dict:
    d = dict(row)
    rc = d.get("reference_contexts")
    d["reference_contexts"] = json.loads(rc) if rc else []
    d.setdefault("category", "")
    return d


# --- Legacy endpoints ---


@router.post("/generate-testset")
async def generate_testset(req: TestGenRequest):
    from evaluation.metrics.testgen import (
        generate_testset_from_chunks,
        generate_testset_with_personas,
    )

    if req.use_personas:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: generate_testset_with_personas(
                chunks=req.chunks,
                testset_size=req.testset_size,
                num_personas=req.num_personas,
                custom_personas=req.custom_personas,
            ),
        )
        return result
    else:
        questions = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: generate_testset_from_chunks(
                chunks=req.chunks,
                testset_size=req.testset_size,
                custom_personas=req.custom_personas,
            ),
        )
        return {"personas": [], "questions": questions}


@router.post("/upload-document")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
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
    from evaluation.metrics.testgen import generate_project_testset

    conn = db.init.get_db()

    # Validate project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
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

    # Guard: chunk count limit (0 = no limit)
    if MAX_CHUNKS_FOR_GENERATION > 0 and len(chunk_rows) > MAX_CHUNKS_FOR_GENERATION:
        raise HTTPException(
            status_code=422,
            detail=f"Too many chunks ({len(chunk_rows)}). Maximum {MAX_CHUNKS_FOR_GENERATION} supported for test generation.",
        )

    chunks = [r["content"] for r in chunk_rows]

    # Sample chunks if requested
    total_chunks = len(chunks)
    if req.chunk_sample_size > 0 and req.chunk_sample_size < total_chunks:
        chunks = random.sample(chunks, req.chunk_sample_size)

    # Auto-generate name if not provided
    name = req.name or f"Test Set ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

    # Insert test_set row
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
        "sampled_chunks": len(chunks),
    }
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
        (project_id, name, json.dumps(generation_config)),
    )
    conn.commit()
    test_set_id = cursor.lastrowid

    # Generate questions — rollback test_set on failure
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: generate_project_testset(
                chunks=chunks,
                testset_size=req.testset_size,
                use_personas=req.use_personas,
                num_personas=req.num_personas,
                custom_personas=req.custom_personas,
                query_distribution=req.query_distribution,
                num_workers=req.num_workers,
                question_categories=req.question_categories,
                project_id=project_id,
            ),
        )
    except Exception as e:
        # Rollback: remove the test_set row so no orphan persists
        conn.execute("DELETE FROM test_sets WHERE id = ?", (test_set_id,))
        conn.commit()
        err_msg = str(e).lower()
        if "rate limit" in err_msg or "rate_limit" in err_msg:
            raise HTTPException(
                status_code=429,
                detail="LLM rate limit exceeded during test generation",
            )
        logger.exception(
            "Test set generation failed for test_set_id=%d", test_set_id
        )
        raise HTTPException(
            status_code=502, detail=f"Test generation failed: {e}"
        )

    # Insert questions
    questions = result.get("questions", [])
    personas = result.get("personas", [])
    persona_map = {p["name"]: p for p in personas} if personas else {}

    inserted_questions = []
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
        inserted_questions.append(
            {
                "question": q.get("user_input", ""),
                "reference_answer": q.get("reference", ""),
                "reference_contexts": q.get("reference_contexts", []),
                "question_type": q.get("synthesizer_name", ""),
                "persona": persona_name,
                "category": category,
                "status": "pending",
            }
        )
    conn.commit()

    return {
        "id": test_set_id,
        "name": name,
        "project_id": project_id,
        "question_count": len(inserted_questions),
        "personas": personas,
        "questions": inserted_questions,
    }


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
        },
    }
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
        (project_id, set_name, json.dumps(generation_config)),
    )
    conn.commit()
    test_set_id = cursor.lastrowid

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

        conn.execute(
            """INSERT INTO test_questions
               (test_set_id, question, reference_answer, reference_contexts, question_type, persona, status)
               VALUES (?, ?, ?, ?, 'uploaded', '', 'pending')""",
            (
                test_set_id,
                row[question_column].strip(),
                row[answer_column].strip(),
                json.dumps(ref_ctx),
            ),
        )
        inserted.append(
            {
                "question": row[question_column].strip(),
                "reference_answer": row[answer_column].strip(),
                "reference_contexts": ref_ctx,
                "question_type": "uploaded",
                "status": "pending",
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


@router.get("/projects/{project_id}/test-sets/generation-progress")
async def generation_progress(project_id: int):
    from evaluation.metrics.testgen import get_progress

    progress = get_progress(project_id)
    if progress is None:
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
    conn.execute(
        """UPDATE test_questions
           SET status = ?, user_edited_answer = ?, user_notes = ?, reviewed_at = datetime('now', 'localtime')
           WHERE id = ?""",
        (req.status, req.user_edited_answer, req.user_notes, question_id),
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
            f"UPDATE test_questions SET status = ?, reviewed_at = datetime('now', 'localtime') WHERE id IN ({placeholders}) AND test_set_id = ?",
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
            "UPDATE test_questions SET status = ?, reviewed_at = datetime('now', 'localtime') WHERE test_set_id = ? AND status = 'pending'",
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


# --- Knowledge Graph Cache Routes ---


@router.get("/projects/{project_id}/knowledge-graph")
async def get_knowledge_graph_info(project_id: int):
    """Return metadata about the cached knowledge graph for a project."""
    from evaluation.metrics.testgen import get_kg_info

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    info = get_kg_info(project_id)
    if info is None:
        return {"exists": False}
    return {"exists": True, **info}


@router.delete("/projects/{project_id}/knowledge-graph", status_code=204)
async def delete_knowledge_graph(project_id: int):
    """Delete the cached knowledge graph for a project."""
    from evaluation.metrics.testgen import delete_kg_from_db

    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    deleted = delete_kg_from_db(project_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail="No knowledge graph found for this project"
        )
    return None
