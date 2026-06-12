"""Scripted user replies with keyword matching.

Different models ask a skill's clarifying questions in different orders — or
skip some entirely — so consuming scripted replies strictly in order pairs
the wrong answer with the wrong question. Lines support two shapes:

    keyword => answer    matched to whichever question CONTAINS the keyword
    answer               positional fallback, consumed in order

When the model asks a question, keyed lines are checked first (first unused
match wins, case-insensitive); otherwise the next unused plain line is used.
Returns None when nothing fits — the caller pauses for the human or hands
off to the LLM user-simulator. ``->`` works as a separator too.
"""

_SEPARATORS = ("=>", "->")


class ScriptedReplies:
    def __init__(self, lines: list[str]) -> None:
        self._entries: list[dict] = []
        for raw in lines:
            line = str(raw).strip()
            if not line:
                continue
            entry = {"key": None, "answer": line, "used": False}
            for sep in _SEPARATORS:
                key, found, answer = line.partition(sep)
                if found and key.strip() and answer.strip():
                    entry = {"key": key.strip().lower(), "answer": answer.strip(), "used": False}
                    break
            self._entries.append(entry)

    def take(self, question: str) -> str | None:
        """Best unused reply for *question*, or None when nothing fits."""
        q = (question or "").lower()
        if q:
            for entry in self._entries:
                if not entry["used"] and entry["key"] and entry["key"] in q:
                    entry["used"] = True
                    return entry["answer"]
        for entry in self._entries:
            if not entry["used"] and entry["key"] is None:
                entry["used"] = True
                return entry["answer"]
        return None

    def __bool__(self) -> bool:
        return any(not e["used"] for e in self._entries)
