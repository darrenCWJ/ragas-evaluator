"""Entry point for the Ragas Evaluator API.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging

from dotenv import load_dotenv

load_dotenv()

# Ensure app loggers output to console (uvicorn only shows its own by default)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

from app import app  # noqa: E402

__all__ = ["app"]
