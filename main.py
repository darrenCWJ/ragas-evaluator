"""Entry point for the Ragas Evaluator API.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import sys
import types

# Shim: ragas unconditionally imports langchain_community.chat_models.vertexai
# which was removed in newer langchain-community versions. Inject a stub module
# so the import doesn't crash at startup (we don't use VertexAI).
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _stub = types.ModuleType("langchain_community.chat_models.vertexai")
    _stub.ChatVertexAI = None  # type: ignore[attr-defined]
    sys.modules["langchain_community.chat_models.vertexai"] = _stub

import logging

from dotenv import load_dotenv

load_dotenv()

# Ensure app loggers output to console (uvicorn only shows its own by default).
# Every record carries the per-request id (see app/services/request_context.py)
# so one request's log lines can be grepped together; "-" outside a request.
# The formatter default covers records emitted during app import, before the
# RequestIDFilter (which lives inside the app package) can be attached.
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(
    logging.Formatter(
        "%(levelname)s:%(name)s:[%(request_id)s] %(message)s",
        defaults={"request_id": "-"},
    )
)
logging.basicConfig(level=logging.INFO, handlers=[_console_handler])

from app import app  # noqa: E402
from app.services.request_context import RequestIDFilter  # noqa: E402

_console_handler.addFilter(RequestIDFilter())

__all__ = ["app"]
