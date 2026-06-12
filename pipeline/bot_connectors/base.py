"""Base types and protocol for bot connectors.

All connectors return a unified BotResponse so the experiment runner
and evaluators can treat every bot identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Citation:
    """A single source citation returned by a bot."""

    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    datasource: str | None = None
    container: str | None = None


@dataclass(frozen=True)
class BotResponse:
    """Normalised response from any bot connector."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)


class BotConnector(Protocol):
    """Interface every bot connector must satisfy.

    ``system_context`` carries per-call system instructions (e.g. a skill
    file under test) and is prepended to any connector-configured system
    prompt. Connectors without a system channel (CSV, Glean) raise
    ``SystemContextUnsupported`` when it is provided.
    """

    async def query(self, question: str, *, system_context: str | None = None) -> BotResponse: ...


class SystemContextUnsupported(RuntimeError):
    """Raised when a connector cannot carry per-call system instructions."""

    def __init__(self, connector_type: str) -> None:
        super().__init__(
            f"The '{connector_type}' connector does not support system context "
            "(skill injection requires a chat-style connector)."
        )


# Instruction appended to the system prompt when the user opts in to
# "prompt for sources".  Connectors that don't natively return citations
# can inject this so the LLM cites its sources in-line.
SOURCE_PROMPT_SUFFIX = (
    "\n\nIMPORTANT: When answering, cite your sources. "
    "For each claim, include a numbered reference like [1], [2], etc. "
    "At the end of your answer, list all references with their URLs if available. "
    "Format: [n] Title - URL"
)
