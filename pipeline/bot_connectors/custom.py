"""Custom endpoint bot connector.

Lets users point the evaluator at any HTTP API by providing:
- endpoint URL
- HTTP method
- headers (JSON)
- request body template (with ``{{question}}`` placeholder)
- JSONPath expressions to extract the answer and optional citations
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import jsonpath_ng.ext as jp

from pipeline.bot_connectors.base import BotResponse, Citation

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0
_PLACEHOLDER_RE = re.compile(r"\{\{\s*question\s*\}\}")

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _validate_endpoint_url(url: str) -> None:
    """Raise ValueError if the URL targets a private/internal address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Endpoint URL must use http or https scheme, got: {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Endpoint URL must include a hostname")
    if hostname.lower() in ("localhost", "0.0.0.0"):
        raise ValueError(f"Endpoint URL hostname {hostname!r} is not allowed")
    try:
        addr = ipaddress.ip_address(hostname)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                raise ValueError(f"Endpoint URL targets a private/internal address: {hostname}")
    except ValueError as e:
        if "is not allowed" in str(e) or "private" in str(e) or "scheme" in str(e) or "hostname" in str(e):
            raise
        # Not an IP address — hostname DNS resolution happens at request time; allow it


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
        _validate_endpoint_url(endpoint_url)
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
