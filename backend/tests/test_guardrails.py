"""Tests for guardrail HTTP shaping (Epic 6).

A minimal throwaway FastAPI app registers the guardrail handlers and exposes one route per
guardrail error. Driving it with the TestClient confirms each error becomes the right status
(422/429/409), carries the system-voice message, and — for the rate limit — sets the
``Retry-After`` header.
"""

import pytest
from app.queue.protocol import QueueFullError
from app.services.guardrails import (
    QUEUE_AT_CAPACITY_MESSAGE,
    InvalidSubmissionError,
    RateLimitedError,
    register_guardrail_handlers,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """A tiny app whose routes raise each guardrail error, with the handlers registered."""
    app = FastAPI()
    register_guardrail_handlers(app)

    @app.get("/cap")
    async def _cap():
        raise InvalidSubmissionError("[ERR] --count exceeds cap (max 100)")

    @app.get("/rate")
    async def _rate():
        raise RateLimitedError(5, "[WARN] rate limit: 1 submission / 5s")

    @app.get("/full")
    async def _full():
        raise QueueFullError("queue at capacity (1000 queued)")

    return TestClient(app)


def test_invalid_submission_becomes_422(client):
    response = client.get("/cap")
    assert response.status_code == 422
    assert response.json()["detail"] == "[ERR] --count exceeds cap (max 100)"


def test_rate_limited_becomes_429_with_retry_after(client):
    response = client.get("/rate")
    assert response.status_code == 429
    assert response.json()["detail"] == "[WARN] rate limit: 1 submission / 5s"
    assert response.json()["retry_after_seconds"] == 5
    assert response.headers["Retry-After"] == "5"


def test_queue_full_becomes_409_at_capacity(client):
    response = client.get("/full")
    assert response.status_code == 409
    assert response.json()["detail"] == QUEUE_AT_CAPACITY_MESSAGE
