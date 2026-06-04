"""Guardrail errors and their HTTP shaping (TDD §5.8, §5.9).

When a guest hits a limit — an invalid batch size, acting too fast, or a full queue — the
api must reject the request clearly rather than degrade for everyone. This module is the
single home for those rejection errors and for turning each one into the right HTTP response
in the system voice the UI renders (e.g. ``[ERR] --count exceeds cap (max 100)``).

Keeping the exceptions here (not inside ``rate_limit.py`` / ``validation.py``) lets both of
those import the error types without importing each other, so there is no import cycle.

Status mapping:
- :class:`InvalidSubmissionError` → ``422`` (the batch fails validation, e.g. > 100 or < 1).
- :class:`RateLimitedError`       → ``429`` with a ``Retry-After`` header (acting too fast).
- :class:`QueueFullError`         → ``409`` (the shared queue is at capacity).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.queue.protocol import QueueFullError

# The shared rejection message when the system-wide queue is full (TDD §5.9). The UI shows a
# `[ AT CAPACITY ]` pane state off the back of the matching 409.
QUEUE_AT_CAPACITY_MESSAGE = "[ERR] queue at capacity"


class InvalidSubmissionError(Exception):
    """A batch fails submission validation (e.g. count over the cap or below 1), giving a 422.

    Carries an already-shaped system-voice ``message`` so the route doesn't have to know the
    wording (e.g. ``[ERR] --count exceeds cap (max 100)``).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RateLimitedError(Exception):
    """A session acted faster than its per-session limit allows, giving a 429.

    ``retry_after_seconds`` is how long the caller should wait before trying again; it is
    echoed both in the body and in the ``Retry-After`` header. ``message`` is the shaped
    system-voice warning (e.g. ``[WARN] rate limit: 1 submission / 5s``).
    """

    def __init__(self, retry_after_seconds: int, message: str) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.message = message


async def _handle_invalid_submission(
    request: Request, error: InvalidSubmissionError
) -> JSONResponse:
    """Shape a submission-validation failure as ``422`` with the message in ``detail``."""
    return JSONResponse(status_code=422, content={"detail": error.message})


async def _handle_rate_limited(request: Request, error: RateLimitedError) -> JSONResponse:
    """Shape a rate-limit hit as ``429`` with a ``Retry-After`` header (TDD §5.9)."""
    return JSONResponse(
        status_code=429,
        content={"detail": error.message, "retry_after_seconds": error.retry_after_seconds},
        headers={"Retry-After": str(error.retry_after_seconds)},
    )


async def _handle_queue_full(request: Request, error: QueueFullError) -> JSONResponse:
    """Shape a full-queue rejection as ``409`` (graceful saturation, TDD §5.9).

    The body uses the fixed ``QUEUE_AT_CAPACITY_MESSAGE`` the UI keys its ``[ AT CAPACITY ]``
    pane off, intentionally not echoing the error's own ``(N queued)`` count — the exact
    number isn't shown to guests.
    """
    return JSONResponse(status_code=409, content={"detail": QUEUE_AT_CAPACITY_MESSAGE})


def register_guardrail_handlers(app: FastAPI) -> None:
    """Wire the guardrail errors to their HTTP responses on the app.

    Registering these once means any route can simply raise the guardrail error and get a
    consistent, system-voiced response — the producer endpoints (Epic 7) and chaos endpoints
    (Epic 12) all reuse this shaping.
    """
    app.add_exception_handler(InvalidSubmissionError, _handle_invalid_submission)
    app.add_exception_handler(RateLimitedError, _handle_rate_limited)
    app.add_exception_handler(QueueFullError, _handle_queue_full)
