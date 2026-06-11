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

# Ensure app loggers output to console (uvicorn only shows its own by default)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

from app import app  # noqa: E402

__all__ = ["app"]
