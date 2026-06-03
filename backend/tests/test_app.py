"""Smoke tests for the FastAPI app boot, health, and session endpoint (Epic 5).

Uses FastAPI's ``TestClient`` as a context manager so the app's lifespan actually runs
(startup opens the lazy Redis/Postgres clients; shutdown closes them). No live datastores
are needed — the clients only connect on first command, which these routes never trigger.
"""

from __future__ import annotations

from app.main import app
from app.services.identity import GUEST_COLORS
from fastapi.testclient import TestClient


def test_app_boots_and_health_is_ok():
    """The app starts (lifespan runs) and ``GET /health`` returns 200 ``{"status": "ok"}``."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_session_returns_a_valid_identity():
    """``POST /api/session`` returns ``{session_id, guest_handle, color}`` in valid shape."""
    with TestClient(app) as client:
        response = client.post("/api/session")
    assert response.status_code == 200

    body = response.json()
    assert set(body) == {"session_id", "guest_handle", "color"}
    assert body["session_id"]

    color_name = body["guest_handle"].removeprefix("guest-")
    assert color_name in GUEST_COLORS
    assert body["color"] == GUEST_COLORS[color_name]
