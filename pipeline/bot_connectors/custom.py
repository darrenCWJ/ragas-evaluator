"""Custom endpoint bot connector.

Lets users point the evaluator at any HTTP API by providing:
- endpoint URL
- HTTP method
- headers (JSON)
- request body template (with ``{{question}}`` placeholder)
- JSONPath expressions to extract the answer and optional citations
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
import jsonpath_ng.ext as jp

from pipeline.bot_connectors.base import BotResponse, Citation

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0
_PLACEHOLDER_RE = re.compile(r"\{\{\s*question\s*\}\}")


class CustomBotConnector:
    """Connector for arbitrary HTTP chatbot endpoints."""

    def __init__(
        self,
        endpoint_url: str,
        http_method: str = "POST",
        headers: dict[str, str] | None = None,
        request_body_template: str = '{"question": "{{question}}"}',
        response_answer_path: str = "$.answer",
        response_citations_path: str | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._http_method = http_method.upper()
        self._headers = headers or {}
        self._body_template = request_body_template
        self._answer_path = jp.parse(response_answer_path)
        self._citations_path = (
            jp.parse(response_citations_path) if response_citations_path else None
        )
        self._timeout = timeout

    async def query(self, question: str) -> BotResponse:
        body_str = _PLACEHOLDER_RE.sub(_escape_json_value(question), self._body_template)
        body = json.loads(body_str)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                self._http_method,
                self._endpoint_url,
                json=body,
                headers=self._headers,
            )
            resp.raise_for_status()

        data = resp.json()

        # Extract answer via JSONPath
        answer_matches = self._answer_path.find(data)
        answer = str(answer_matches[0].value) if answer_matches else ""

        # Extract citations via JSONPath (optional)
        citations: list[Citation] = []
        if self._citations_path:
            cit_matches = self._citations_path.find(data)
            for m in cit_matches:
                val = m.value
                if isinstance(val, dict):
                    citations.append(
                        Citation(
                            title=val.get("title"),
                            url=val.get("url"),
                            snippet=val.get("snippet"),
                        )
                    )
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            citations.append(
                                Citation(
                                    title=item.get("title"),
                                    url=item.get("url"),
                                    snippet=item.get("snippet"),
                                )
                            )

        return BotResponse(answer=answer, citations=citations, raw_response=data)


def _escape_json_value(value: str) -> str:
    """Escape a string so it is safe to substitute into a JSON template.

    We use json.dumps to get proper escaping (handles quotes, newlines,
    etc.) then strip the surrounding quotes since the template already
    has them.
    """
    return json.dumps(value)[1:-1]
