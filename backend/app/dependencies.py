"""FastAPI dependency providers that hand routes the shared datastore clients.

The lifespan in :mod:`app.main` opens one Redis queue client, one Postgres database client,
and one rate limiter onto ``app.state``; these providers read them back so every route reuses
the same connection pools. They live in their own module (not :mod:`app.main`) so routers can
import them without importing the app object — which would be an import cycle, since
:mod:`app.main` imports the routers.
"""

from __future__ import annotations

from fastapi import Request, WebSocket

from app.db.engine import Database
from app.queue.client import JobQueue
from app.realtime.connection_manager import ConnectionManager
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore


def get_queue(request: Request) -> JobQueue:
    """Provide the shared queue client to a route (FastAPI dependency)."""
    return request.app.state.queue


def get_database(request: Request) -> Database:
    """Provide the shared database client to a route (FastAPI dependency)."""
    return request.app.state.database


def get_rate_limiter(request: Request) -> RateLimiter:
    """Provide the shared rate limiter to a route (FastAPI dependency)."""
    return request.app.state.rate_limiter


def get_session_store(request: Request) -> SessionStore:
    """Provide the shared guest-session store to a route (FastAPI dependency)."""
    return request.app.state.session_store


def get_connection_manager(websocket: WebSocket) -> ConnectionManager:
    """Provide the shared WebSocket connection manager to the ``/ws`` route.

    Takes a :class:`WebSocket` rather than a :class:`Request` because it is only ever resolved
    inside the WebSocket route — both reach the shared instance through the same ``app.state``.
    """
    return websocket.app.state.connection_manager
