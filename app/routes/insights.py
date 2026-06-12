"""Transparency insights — test set quality audit, corpus coverage, and
per-category experiment breakdowns.

These endpoints exist so a user can answer "can I trust this test set?" and
"WHAT went wrong?" instead of staring at one averaged score.
"""

import json
import logging
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db.init
from evaluation.testset_quality import audit_test_set, summarize_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["insights"])

# On-the-fly coverage matching is bounded — beyond this many chunks, only
# questions with stored provenance are counted.
_MAX_FALLBACK_CHUNKS = 20_000


def _require(conn, sql: str, params: tuple, error: str):
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=error)
    return row


def _sanitize(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


# ---------------------------------------------------------------------------
# Test set quality audit
# ---------------------------------------------------------------------------


class QualityAuditRequest(BaseModel):
    use_llm: bool = True


@router.post("/projects/{project_id}/test-sets/{test_set_id}/quality-audit")
async def run_quality_audit(project_id: int, test_set_id: int, req: QualityAuditRequest):
    """Audit every question in the test set and persist per-question results.

    Writes ``metadata.quality = {score, flags, reasoning}`` on each question
    and returns the aggregate summary. Works for generated and uploaded sets.
    """
    conn = db.init.get_db()
    _require(
        conn,
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
        "Test set not found",
    )
    rows = conn.execute(
        "SELECT id, question, reference_answer, reference_contexts, question_type, metadata_json "
        "FROM test_questions WHERE test_set_id = ?",
        (test_set_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="Test set has no questions")

    questions = []
    for r in rows:
        questions.append({
            "id": r["id"],
            "question": r["question"],
            "reference_answer": r["reference_answer"],
            "reference_contexts": json.loads(r["reference_contexts"]) if r["reference_contexts"] else [],
            "question_type": r["question_type"] or "",
            "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
        })

    assessments = await audit_test_set(questions, use_llm=req.use_llm)

    by_id = {q["id"]: q for q in questions}
    for qid, assessment in assessments:
        metadata = by_id[qid]["metadata"]
        metadata["quality"] = assessment
        conn.execute(
            "UPDATE test_questions SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata), qid),
        )
    conn.commit()

    summary = summarize_audit(assessments)
    summary["use_llm"] = req.use_llm
    return summary


# ---------------------------------------------------------------------------
# Corpus coverage
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/test-sets/{test_set_id}/coverage")
async def test_set_coverage(project_id: int, test_set_id: int):
    """How much of the corpus does this test set actually exercise?

    Uses stored question provenance (``metadata.source_chunk_ids``); for
    legacy questions without provenance, falls back to content matching when
    the corpus is small enough.
    """
    conn = db.init.get_db()
    _require(
        conn,
        "SELECT id FROM test_sets WHERE id = ? AND project_id = ?",
        (test_set_id, project_id),
        "Test set not found",
    )

    q_rows = conn.execute(
        "SELECT id, reference_contexts, metadata_json FROM test_questions WHERE test_set_id = ?",
        (test_set_id,),
    ).fetchall()

    covered_chunks: set[int] = set()
    covered_docs: dict[int, int] = {}  # document_id -> question count
    unmatched_questions = 0

    # Fallback lookup over the whole project corpus (bounded)
    chunk_rows = conn.execute(
        """SELECT c.id, c.document_id, c.content FROM chunks c
           JOIN chunk_configs cc ON cc.id = c.chunk_config_id
           WHERE cc.project_id = ?""",
        (project_id,),
    ).fetchall()
    fallback: dict[str, tuple[int, int]] = {}
    if len(chunk_rows) <= _MAX_FALLBACK_CHUNKS:
        for c in chunk_rows:
            fallback[" ".join((c["content"] or "").split())] = (c["id"], c["document_id"])

    for q in q_rows:
        meta = json.loads(q["metadata_json"]) if q["metadata_json"] else {}
        chunk_ids = meta.get("source_chunk_ids") or []
        doc_ids = meta.get("source_document_ids") or []
        if not chunk_ids and fallback:
            contexts = json.loads(q["reference_contexts"]) if q["reference_contexts"] else []
            for ctx in contexts:
                text = ctx if isinstance(ctx, str) else ctx.get("content", "")
                hit = fallback.get(" ".join((text or "").split()))
                if hit:
                    chunk_ids.append(hit[0])
                    if hit[1] not in doc_ids:
                        doc_ids.append(hit[1])
        if not chunk_ids and not doc_ids:
            unmatched_questions += 1
            continue
        covered_chunks.update(chunk_ids)
        for did in doc_ids:
            covered_docs[did] = covered_docs.get(did, 0) + 1

    doc_rows = conn.execute(
        "SELECT id, filename FROM documents WHERE project_id = ?", (project_id,)
    ).fetchall()
    documents = [
        {
            "document_id": d["id"],
            "filename": d["filename"],
            "question_count": covered_docs.get(d["id"], 0),
            "covered": d["id"] in covered_docs,
        }
        for d in doc_rows
    ]
    uncovered = [d for d in documents if not d["covered"]]

    total_chunks = len(chunk_rows)
    return {
        "total_questions": len(q_rows),
        "questions_with_provenance": len(q_rows) - unmatched_questions,
        "total_documents": len(doc_rows),
        "covered_documents": len(covered_docs),
        "uncovered_documents": [d["filename"] for d in uncovered],
        "total_chunks": total_chunks,
        "covered_chunks": len(covered_chunks),
        "chunk_coverage": round(len(covered_chunks) / total_chunks, 3) if total_chunks else None,
        "documents": documents,
    }


# ---------------------------------------------------------------------------
# Per-category experiment breakdown
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/experiments/{experiment_id}/breakdown")
async def experiment_breakdown(project_id: int, experiment_id: int):
    """Score breakdown by question category — the 'what went wrong' view.

    Groups results by question category (falling back to question_type),
    returning per-metric averages, counts, and the weakest questions per
    group so users see WHERE their agent fails, not just the overall mean.
    """
    conn = db.init.get_db()
    _require(
        conn,
        "SELECT id FROM experiments WHERE id = ? AND project_id = ?",
        (experiment_id, project_id),
        "Experiment not found",
    )

    rows = conn.execute(
        """SELECT er.test_question_id, er.metrics_json, er.metadata_json AS result_meta,
                  tq.question, tq.category, tq.question_type, tq.metadata_json AS q_meta
           FROM experiment_results er
           JOIN test_questions tq ON tq.id = er.test_question_id
           WHERE er.experiment_id = ?""",
        (experiment_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="Experiment has no results")

    groups: dict[str, dict] = {}
    for r in rows:
        q_meta = json.loads(r["q_meta"]) if r["q_meta"] else {}
        if q_meta.get("expected_behavior") == "refusal":
            group_name = "out_of_knowledge_base"
        else:
            group_name = r["category"] or r["question_type"] or "uncategorized"
        g = groups.setdefault(group_name, {
            "totals": {}, "counts": {}, "questions": [],
        })

        metrics = json.loads(r["metrics_json"]) if r["metrics_json"] else {}
        valid = []
        for name, value in metrics.items():
            value = _sanitize(value)
            if value is None:
                continue
            g["totals"][name] = g["totals"].get(name, 0.0) + value
            g["counts"][name] = g["counts"].get(name, 0) + 1
            valid.append(value)
        g["questions"].append({
            "question_id": r["test_question_id"],
            "question": r["question"][:200],
            "mean_score": round(sum(valid) / len(valid), 4) if valid else None,
        })

    out = []
    for name, g in groups.items():
        metric_avgs = {
            m: round(g["totals"][m] / g["counts"][m], 4)
            for m in g["totals"]
            if g["counts"][m] > 0
        }
        scored = [q for q in g["questions"] if q["mean_score"] is not None]
        scored.sort(key=lambda q: q["mean_score"])
        overall_vals = list(metric_avgs.values())
        out.append({
            "category": name,
            "question_count": len(g["questions"]),
            "overall": round(sum(overall_vals) / len(overall_vals), 4) if overall_vals else None,
            "metrics": metric_avgs,
            "weakest_questions": scored[:3],
        })
    out.sort(key=lambda c: (c["overall"] is None, c["overall"]))
    return {"categories": out}
