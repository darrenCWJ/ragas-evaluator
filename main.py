"""Entry point for the Ragas Evaluator API.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from dotenv import load_dotenv

load_dotenv()

from app import app  # noqa: E402

__all__ = ["app"]
