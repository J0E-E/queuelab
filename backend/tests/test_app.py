"""Smoke tests for the FastAPI app boot, health, and session endpoint (Epic 5).

Uses FastAPI's ``TestClient`` as a context manager so the app's lifespan actually runs
(startup opens the lazy Redis/Postgres clients; shutdown closes them). No live datastores
are needed — the clients only connect on first command, which these routes never trigger.
"""

from __future__ import annotations

from app.dependencies import get_rate_limiter, get_session_store
from app.main import app
from app.services.identity import GUEST_COLORS
from fastapi.testclient import TestClient


class _NoopSessionStore:
    """A stand-in session store that skips the Redis write, so this smoke test needs no
    container; the endpoint's persistence is exercised in the integration suite."""

    async def save(self, identity) -> None:
        return None


class _NoopRateLimiter:
    """A stand-in rate limiter that always allows, so this smoke test needs no container;
    the real throttling is exercised in the integration suite."""

    async def check_session(self, client_ip) -> None:
        return None


def test_app_boots_and_health_is_ok():
    """The app starts (lifespan runs) and ``GET /health`` returns 200 ``{"status": "ok"}``."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lifespan_runs_and_cancels_the_reaper():
    """The lifespan starts the reaper task on boot and cancels it cleanly on shutdown.

    The default 2s tick means no sweep fires inside this brief context, so the loop never
    touches Redis — only its start/cancel lifecycle is exercised here (no container needed).
    """
    with TestClient(app):
        reaper_task = app.state.reaper_task
        assert not reaper_task.done()
    assert reaper_task.cancelled()


def test_lifespan_runs_and_cancels_the_durable_writer():
    """The lifespan starts the durable-writer task on boot and cancels it cleanly on shutdown.

    With no reachable Redis here, the writer's first subscribe fails and it re-subscribes on a
    pause loop, so the task is always mid-flight (never finished) when shutdown cancels it —
    exercising only its start/cancel lifecycle, no container needed.
    """
    with TestClient(app):
        durable_writer_task = app.state.durable_writer_task
        assert not durable_writer_task.done()
    assert durable_writer_task.cancelled()


def test_create_session_returns_a_valid_identity():
    """``POST /api/session`` returns ``{session_id, guest_handle, color}`` in valid shape."""
    app.dependency_overrides[get_session_store] = lambda: _NoopSessionStore()
    app.dependency_overrides[get_rate_limiter] = lambda: _NoopRateLimiter()
    try:
        with TestClient(app) as client:
            response = client.post("/api/session")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200

    body = response.json()
    assert set(body) == {"session_id", "guest_handle", "color"}
    assert body["session_id"]

    color_name = body["guest_handle"].removeprefix("guest-")
    assert color_name in GUEST_COLORS
    assert body["color"] == GUEST_COLORS[color_name]
