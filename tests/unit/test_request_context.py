"""Unit tests for the request-ID middleware and log-correlation filter."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.request_context import (
    REQUEST_ID_HEADER,
    RequestIDFilter,
    RequestIDMiddleware,
    current_request_id,
    request_id_var,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/echo")
    async def echo():
        return {"request_id": current_request_id()}

    return TestClient(app)


def _record() -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)


class TestRequestIDMiddleware:
    def test_generates_id_and_echoes_header(self, client):
        res = client.get("/echo")
        rid = res.headers[REQUEST_ID_HEADER]
        assert len(rid) == 8
        # The handler saw the same id the client received.
        assert res.json()["request_id"] == rid

    def test_fresh_id_per_request(self, client):
        first = client.get("/echo").headers[REQUEST_ID_HEADER]
        second = client.get("/echo").headers[REQUEST_ID_HEADER]
        assert first != second

    def test_honours_safe_inbound_header(self, client):
        res = client.get("/echo", headers={REQUEST_ID_HEADER: "trace-123.A_b"})
        assert res.headers[REQUEST_ID_HEADER] == "trace-123.A_b"
        assert res.json()["request_id"] == "trace-123.A_b"

    def test_replaces_unsafe_inbound_header(self, client):
        res = client.get("/echo", headers={REQUEST_ID_HEADER: "bad id with spaces"})
        rid = res.headers[REQUEST_ID_HEADER]
        assert rid != "bad id with spaces"
        assert len(rid) == 8

    def test_replaces_oversized_inbound_header(self, client):
        res = client.get("/echo", headers={REQUEST_ID_HEADER: "x" * 65})
        assert len(res.headers[REQUEST_ID_HEADER]) == 8

    def test_context_cleared_after_request(self, client):
        client.get("/echo")
        assert current_request_id() is None


class TestRequestIDFilter:
    def test_stamps_current_id(self):
        record = _record()
        token = request_id_var.set("abc12345")
        try:
            assert RequestIDFilter().filter(record) is True
            assert record.request_id == "abc12345"
        finally:
            request_id_var.reset(token)

    def test_dash_outside_request_context(self):
        record = _record()
        RequestIDFilter().filter(record)
        assert record.request_id == "-"
