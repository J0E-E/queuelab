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
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

# Re-exported here so existing imports of ``app.main.get_queue`` keep working; the providers
# themselves live in app.dependencies to avoid an import cycle with the routers.
from app.config import settings
from app.db.engine import Database
from app.dependencies import get_database, get_queue, get_rate_limiter, get_session_store
from app.queue.client import JobQueue
from app.reaper import run_reaper
from app.routers import jobs, session
from app.services.guardrails import register_guardrail_handlers
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore

__all__ = ["app", "get_database", "get_queue", "get_rate_limiter", "get_session_store"]

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the Redis and Postgres clients on startup, close them on shutdown."""
    app.state.queue = JobQueue.from_settings()
    app.state.database = Database.from_settings()
    app.state.rate_limiter = RateLimiter.from_settings()
    app.state.session_store = SessionStore.from_settings()
    # The reaper sweeps Redis on a tick to promote due delayed jobs and requeue expired
    # leases (Epic 9). It runs for the life of the process and is cancelled on shutdown.
    reaper_task = asyncio.create_task(
        run_reaper(app.state.queue, interval_seconds=settings.reaper_loop_seconds)
    )
    app.state.reaper_task = reaper_task
    try:
        yield
    finally:
        # Stop the reaper before closing the clients, so an in-flight sweep never hits a
        # closed Redis client.
        reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await reaper_task
        # Close every client independently. Running them together (gather) and keeping
        # any error instead of raising (return_exceptions=True) means a failure closing
        # one client can't skip closing the others and leak their connection pools.
        results = await asyncio.gather(
            app.state.queue.aclose(),
            app.state.database.aclose(),
            app.state.rate_limiter.aclose(),
            app.state.session_store.aclose(),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Error while closing a datastore client on shutdown: %s", result)


app = FastAPI(title="QueueLab API", lifespan=lifespan)
app.include_router(session.router)
app.include_router(jobs.router)
# Turn guardrail errors (caps, rate limits, full queue) into system-voiced HTTP responses.
# The producer endpoints (POST /api/jobs) are the first to raise them.
register_guardrail_handlers(app)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the process is up. Returns 200 without touching the datastores."""
    return {"status": "ok"}
