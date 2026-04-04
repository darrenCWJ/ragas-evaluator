"""Test sets, test questions, and annotation routes."""

import asyncio
import json
import logging
import random
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.models import (
    TestGenRequest,
    PersonaGenRequest,
    TestSetCreate,
    QuestionAnnotation,
    BulkAnnotation,
    VALID_QUESTION_STATUSES,
    BULK_ACTION_TO_STATUS,
    MAX_CHUNKS_FOR_GENERATION,
)
import db.init

router = APIRouter(prefix="/api", tags=["testsets"])
logger = logging.getLogger(__name__)


# --- Helpers ---


def _parse_test_question_row(row) -> dict:
    d = dict(row)
    rc = d.get("reference_contexts")
    d["reference_contexts"] = json.loads(rc) if rc else []
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


@router.post("/generate-personas")
async def gen_personas(req: PersonaGenRequest):
    from evaluation.metrics.testgen import generate_personas

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
        inserted_questions.append(
            {
                "question": q.get("user_input", ""),
                "reference_answer": q.get("reference", ""),
                "reference_contexts": q.get("reference_contexts", []),
                "question_type": q.get("synthesizer_name", ""),
                "persona": persona_name,
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
           SET status = ?, user_edited_answer = ?, user_notes = ?, reviewed_at = CURRENT_TIMESTAMP
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
