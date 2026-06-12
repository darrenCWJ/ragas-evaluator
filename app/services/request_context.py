"""Per-request ID propagation for log correlation.

RequestIDMiddleware assigns every HTTP request a short id (honouring a safe
inbound X-Request-ID header), stores it in a ContextVar, and echoes it back in
the response. RequestIDFilter stamps the id onto every log record emitted
while handling the request, so one request's log lines can be grepped
together. Background tasks spawned during a request (asyncio.create_task)
inherit the id automatically via contextvars.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"

# Accept simple client-supplied ids only (defence against log injection).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    """Short random id — 8 hex chars is plenty for log correlation."""
    return uuid.uuid4().hex[:8]


def current_request_id() -> str | None:
    """The id of the request being handled, or None outside request context."""
    return request_id_var.get()


class RequestIDFilter(logging.Filter):
    """Stamp request_id onto every record ("-" outside request context)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign/propagate the per-request id and echo it in the response."""

    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        rid = supplied if _SAFE_ID_RE.match(supplied) else new_request_id()
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
