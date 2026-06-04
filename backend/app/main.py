"""The FastAPI application: lifespan wiring, health check, and mounted routers (Epic 5).

This is the runnable api process. On startup it opens the shared Redis queue client and
the Postgres database client and stashes them on ``app.state`` so route handlers and
background loops (added in later epics) reuse one connection pool each; on shutdown it
closes both cleanly.

The clients are created lazily — building them does not open a network connection until
the first command — so the app (and the boot smoke test) starts even when Redis/Postgres
are not yet reachable. Health here is intentionally shallow (just "the process is up");
a deeper datastore ping can come later.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.db.engine import Database
from app.queue.client import JobQueue
from app.routers import session
from app.services.guardrails import register_guardrail_handlers
from app.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the Redis and Postgres clients on startup, close them on shutdown."""
    app.state.queue = JobQueue.from_settings()
    app.state.database = Database.from_settings()
    app.state.rate_limiter = RateLimiter.from_settings()
    try:
        yield
    finally:
        # Close every client independently. Running them together (gather) and keeping
        # any error instead of raising (return_exceptions=True) means a failure closing
        # one client can't skip closing the others and leak their connection pools.
        results = await asyncio.gather(
            app.state.queue.aclose(),
            app.state.database.aclose(),
            app.state.rate_limiter.aclose(),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Error while closing a datastore client on shutdown: %s", result)


app = FastAPI(title="QueueLab API", lifespan=lifespan)
app.include_router(session.router)
# Turn guardrail errors (caps, rate limits, full queue) into system-voiced HTTP responses.
# Harmless until a route raises one — the producer endpoints (Epic 7) are the first to.
register_guardrail_handlers(app)


def get_queue(request: Request) -> JobQueue:
    """Provide the shared queue client to a route (FastAPI dependency)."""
    return request.app.state.queue


def get_database(request: Request) -> Database:
    """Provide the shared database client to a route (FastAPI dependency)."""
    return request.app.state.database


def get_rate_limiter(request: Request) -> RateLimiter:
    """Provide the shared rate limiter to a route (FastAPI dependency)."""
    return request.app.state.rate_limiter


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the process is up. Returns 200 without touching the datastores."""
    return {"status": "ok"}
