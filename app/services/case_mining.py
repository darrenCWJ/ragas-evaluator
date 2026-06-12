"""Real-user log import and hard-case mining.

Log import turns raw user queries (txt/csv/json exports from production logs)
into a reference-free test set: trivial and duplicate queries are dropped,
the rest become approved questions with no reference answer (reference-free
metrics still apply, and the questions are real usage).

Hard-case mining closes the loop on failures: take the worst-scoring
questions of a completed experiment, have an LLM write N harder/paraphrased
variants of each, and emit them as a new test set. Variants inherit the
original's reference answer, contexts, and provenance (source_chunk_ids), so
retrieval diagnostics keep working on the mined set.
"""

import asyncio
import json
import logging

from pipeline.llm import chat_completion

logger = logging.getLogger(__name__)

MIN_LOG_QUERY_CHARS = 8
MAX_LOG_QUERIES = 1000

VARIANT_SYSTEM_PROMPT = (
    "You write harder test variants of a question that a RAG assistant answered "
    "poorly. Each variant must ask for the SAME underlying fact or task — the "
    "original reference answer must remain correct — but reworded to be more "
    "challenging: different vocabulary, indirect phrasing, added distractors, "
    "or a more casual/ambiguous register. Return ONLY the variants, one per "
    "line, no numbering or commentary."
)


def clean_log_queries(raw_queries: list[str]) -> tuple[list[str], dict]:
    """Strip, drop trivial (<8 chars) and duplicate queries; cap the total."""
    seen: set[str] = set()
    kept: list[str] = []
    skipped_trivial = 0
    skipped_duplicate = 0
    for raw in raw_queries:
        query = (raw or "").strip()
        if len(query) < MIN_LOG_QUERY_CHARS:
            skipped_trivial += 1
            continue
        key = " ".join(query.lower().split())
        if key in seen:
            skipped_duplicate += 1
            continue
        seen.add(key)
        kept.append(query)
        if len(kept) >= MAX_LOG_QUERIES:
            break
    return kept, {"trivial": skipped_trivial, "duplicate": skipped_duplicate}


def find_hard_cases(conn, experiment_id: int, threshold: float, limit: int) -> list[dict]:
    """Worst-scoring results of an experiment (mean of numeric metrics < threshold)."""
    rows = conn.execute(
        """SELECT er.metrics_json, tq.id AS question_id, tq.question,
                  tq.reference_answer, tq.user_edited_answer,
                  tq.reference_contexts, tq.metadata_json
           FROM experiment_results er
           JOIN test_questions tq ON er.test_question_id = tq.id
           WHERE er.experiment_id = ?""",
        (experiment_id,),
    ).fetchall()

    scored = []
    for row in rows:
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        values = [v for v in metrics.values() if isinstance(v, int | float)]
        if not values:
            continue
        mean_score = sum(values) / len(values)
        if mean_score < threshold:
            scored.append({
                "question_id": row["question_id"],
                "question": row["question"],
                "reference_answer": row["user_edited_answer"] or row["reference_answer"],
                "reference_contexts": row["reference_contexts"],
                "metadata_json": row["metadata_json"],
                "mean_score": round(mean_score, 4),
            })
    scored.sort(key=lambda c: c["mean_score"])
    return scored[:limit]


async def generate_variants(
    question: str, num_variants: int, model: str, llm_params: dict | None = None
) -> list[str]:
    """LLM-generate harder variants of one question. Returns [] on failure."""
    try:
        result = await chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": VARIANT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nGenerate {num_variants} variants.",
                },
            ],
            params=llm_params or {},
        )
        variants = [
            line.strip().lstrip("-•0123456789. ").strip()
            for line in result["content"].splitlines()
            if line.strip()
        ]
        variants = [v for v in variants if v and v.lower() != question.lower()]
        return variants[:num_variants]
    except Exception:
        logger.warning("Variant generation failed for question %r", question[:80], exc_info=True)
        return []


async def mine_hard_cases(
    conn,
    project_id: int,
    experiment_id: int,
    experiment_name: str,
    *,
    threshold: float,
    variants_per_question: int,
    max_questions: int,
    model: str,
) -> dict:
    """Create a hard-case test set from an experiment's worst results."""
    hard_cases = find_hard_cases(conn, experiment_id, threshold, max_questions)
    if not hard_cases:
        return {"test_set_id": None, "hard_cases": 0, "variants_created": 0, "failures": 0}

    semaphore = asyncio.Semaphore(4)

    async def _generate(case: dict) -> tuple[dict, list[str]]:
        async with semaphore:
            return case, await generate_variants(
                case["question"], variants_per_question, model
            )

    results = await asyncio.gather(*(_generate(c) for c in hard_cases))

    generation_config = json.dumps({
        "source": "hard_case_mining",
        "experiment_id": experiment_id,
        "threshold": threshold,
        "variants_per_question": variants_per_question,
        "model": model,
    })
    cursor = conn.execute(
        "INSERT INTO test_sets (project_id, name, generation_config_json) VALUES (?, ?, ?)",
        (project_id, f"Hard cases — {experiment_name}"[:200], generation_config),
    )
    test_set_id = cursor.lastrowid

    variants_created = 0
    failures = 0
    for case, variants in results:
        if not variants:
            failures += 1
            continue
        base_meta = {}
        if case["metadata_json"]:
            try:
                base_meta = json.loads(case["metadata_json"]) or {}
            except (TypeError, ValueError):
                base_meta = {}
        metadata = json.dumps({
            **base_meta,
            "hard_case": True,
            "variant_of_question_id": case["question_id"],
            "source_mean_score": case["mean_score"],
        })
        for variant in variants:
            conn.execute(
                """INSERT INTO test_questions
                   (test_set_id, question, reference_answer, reference_contexts,
                    question_type, status, metadata_json)
                   VALUES (?, ?, ?, ?, 'hard_case_mined', 'approved', ?)""",
                (
                    test_set_id,
                    variant,
                    case["reference_answer"],
                    case["reference_contexts"] or "[]",
                    metadata,
                ),
            )
            variants_created += 1

    if variants_created == 0:
        # Every generation failed — don't leave an empty test set behind.
        conn.execute("DELETE FROM test_sets WHERE id = ?", (test_set_id,))
        conn.commit()
        return {
            "test_set_id": None,
            "hard_cases": len(hard_cases),
            "variants_created": 0,
            "failures": failures,
        }

    conn.commit()
    logger.info(
        "Hard-case mining: experiment %d -> test set %d (%d variants from %d hard cases, %d failures)",
        experiment_id, test_set_id, variants_created, len(hard_cases), failures,
    )
    return {
        "test_set_id": test_set_id,
        "hard_cases": len(hard_cases),
        "variants_created": variants_created,
        "failures": failures,
    }
