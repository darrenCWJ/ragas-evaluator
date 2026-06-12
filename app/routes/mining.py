"""Routes for real-user log import and hard-case mining."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import db.init
from app.models import HardCaseMineRequest
from app.services.case_mining import MAX_LOG_QUERIES, clean_log_queries, mine_hard_cases
from config import DEFAULT_EVAL_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["mining"])

_COMMON_QUERY_KEYS = ("question", "query", "message", "prompt", "text", "input")


def _extract_queries(content: bytes, filename: str, question_column: str | None) -> list[str]:
    """Pull raw query strings out of a txt/csv/json(l) log export."""
    text = content.decode("utf-8-sig", errors="replace")
    lower_name = filename.lower()

    if lower_name.endswith((".csv", ".tsv", ".json", ".jsonl", ".ndjson")):
        from app.routes.testsets import _parse_upload_file

        rows = _parse_upload_file(content, filename)
        if not rows:
            return []
        columns = set(rows[0].keys())
        column = question_column
        if column is None:
            column = next((k for k in _COMMON_QUERY_KEYS if k in columns), None)
        if column is None or column not in columns:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Could not find a query column. Pass question_column. "
                    f"Available: {sorted(columns)}"
                ),
            )
        return [str(row.get(column) or "") for row in rows]

    # Plain text: one query per line
    return text.splitlines()


@router.post("/projects/{project_id}/test-sets/import-logs", status_code=201)
async def import_logs(
    project_id: int,
    file: UploadFile = File(...),
    question_column: str | None = Form(None),
    name: str | None = Form(None),
):
    """Create a reference-free test set from real user query logs.

    Accepts .txt (one query per line), .csv/.tsv, or .json/.jsonl exports.
    Trivial (<8 chars) and duplicate queries are dropped; at most
    1000 queries are imported. Questions carry no reference answer, so use
    reference-free metrics (faithfulness, answer_relevancy, context metrics).
    """
    conn = db.init.get_db()
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="File too large (max 10MB)")

    raw_queries = _extract_queries(content, file.filename or "logs.txt", question_column)
    queries, skipped = clean_log_queries(raw_queries)
    if not queries:
        raise HTTPException(
            status_code=422,
            detail=f"No usable queries found ({skipped['trivial']} trivial, {skipped['duplicate']} duplicate)",
        )

    set_name = name or f"User logs ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    generation_config = json.dumps({
        "source": "log_import",
        "filename": file.filename,
        "imported": len(queries),
        "skipped": skipped,
        "max_queries": MAX_LOG_QUERIES,
    })
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
        (project_id, set_name, generation_config),
    )
    test_set_id = cursor.lastrowid
    for query in queries:
        # reference_answer is NOT NULL in the schema — reference-free questions
        # carry an empty string (use reference-free metrics on these sets).
        conn.execute(
            """INSERT INTO test_questions
               (test_set_id, question, reference_answer, reference_contexts, question_type, status)
               VALUES (?, ?, '', '[]', 'log_import', 'approved')""",
            (test_set_id, query),
        )
    conn.commit()

    return {
        "test_set_id": test_set_id,
        "name": set_name,
        "imported": len(queries),
        "skipped": skipped,
    }


@router.post("/projects/{project_id}/experiments/{experiment_id}/mine-hard-cases", status_code=201)
async def mine_hard_cases_endpoint(
    project_id: int, experiment_id: int, body: HardCaseMineRequest
):
    """Generate harder variants of an experiment's worst-scoring questions."""
    conn = db.init.get_db()
    experiment = conn.execute(
        "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
    ).fetchone()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if experiment["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be completed (current: {experiment['status']})",
        )

    result = await mine_hard_cases(
        conn,
        project_id,
        experiment_id,
        experiment["name"],
        threshold=body.threshold,
        variants_per_question=body.variants_per_question,
        max_questions=body.max_questions,
        model=body.model or DEFAULT_EVAL_MODEL,
    )
    if result["hard_cases"] == 0:
        raise HTTPException(
            status_code=409,
            detail=f"No results scored below {body.threshold} — nothing to mine",
        )
    if result["test_set_id"] is None:
        raise HTTPException(
            status_code=502,
            detail="Variant generation failed for every hard case (LLM errors)",
        )
    return result
