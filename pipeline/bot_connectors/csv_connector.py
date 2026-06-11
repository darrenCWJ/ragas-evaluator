"""CSV bot connector — serves pre-loaded Q&A from external_baselines."""

from __future__ import annotations

from difflib import SequenceMatcher

from pipeline.bot_connectors.base import BotResponse, Citation


class CsvBotConnector:
    """Looks up answers from the external_baselines table by matching question text."""

    def __init__(self, *, bot_config_id: int) -> None:
        self._bot_config_id = bot_config_id
        self._rows: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._rows is not None:
            return self._rows

        import db.init

        conn = db.init.get_db()
        rows = conn.execute(
            "SELECT question, answer, sources FROM external_baselines WHERE bot_config_id = ?",
            (self._bot_config_id,),
        ).fetchall()
        self._rows = [
            {"question": r["question"], "answer": r["answer"], "sources": r["sources"] or ""}
            for r in rows
        ]
        return self._rows

    async def query(self, question: str) -> BotResponse:
        rows = self._load()
        if not rows:
            return BotResponse(answer="[No CSV data found for this bot config]")

        # Find best matching question (exact first, then fuzzy)
        q_lower = question.strip().lower()
        best_row = None
        best_score = 0.0

        for row in rows:
            row_q = row["question"].strip().lower()
            if row_q == q_lower:
                best_row = row
                break
            score = SequenceMatcher(None, q_lower, row_q).ratio()
            if score > best_score:
                best_score = score
                best_row = row

        if best_row is None:
            return BotResponse(answer="[No matching question found in CSV data]")

        citations: list[Citation] = []
        if best_row["sources"]:
            citations = [Citation(snippet=best_row["sources"])]

        return BotResponse(
            answer=best_row["answer"],
            citations=citations,
            raw_response={"source": "csv", "matched_question": best_row["question"]},
        )
