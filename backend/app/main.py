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
from app.realtime.broadcaster import run_broadcaster
from app.realtime.connection_manager import ConnectionManager
from app.realtime.durable_writer import run_durable_writer
from app.realtime.metrics_tick import run_metrics_tick
from app.reaper import run_reaper
from app.routers import jobs, metrics, realtime, session
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
    # The connection manager tracks every open WS /ws client and seeds each with a snapshot on
    # connect (Epic 10b). It holds no background task of its own; the broadcaster below pushes
    # deltas through it for the life of the process.
    app.state.connection_manager = ConnectionManager(app.state.queue)
    # The reaper sweeps Redis on a tick to promote due delayed jobs and requeue expired
    # leases (Epic 9). It runs for the life of the process and is cancelled on shutdown.
    reaper_task = asyncio.create_task(
        run_reaper(app.state.queue, interval_seconds=settings.reaper_loop_seconds)
    )
    app.state.reaper_task = reaper_task
    # The durable-writer subscribes to state-change events and copies each job's outcome onto
    # its durable Postgres row, so completed/failed history survives the Redis hot record's 1h
    # TTL (Epic 10a). Like the reaper it runs for the life of the process and is cancelled on
    # shutdown.
    durable_writer_task = asyncio.create_task(
        run_durable_writer(app.state.queue, app.state.database)
    )
    app.state.durable_writer_task = durable_writer_task
    # The broadcaster subscribes to the same state-change channel and fans each event out to
    # every connected WS /ws client through the connection manager (Epic 10b). Like the reaper
    # and durable-writer it runs for the life of the process and is cancelled on shutdown.
    broadcaster_task = asyncio.create_task(
        run_broadcaster(app.state.queue, app.state.connection_manager)
    )
    app.state.broadcaster_task = broadcaster_task
    # The metrics tick pushes the queue's aggregate vitals (counts + queue depth + worker count)
    # to every connected WS /ws client every ``metrics_tick_seconds`` (Epic 10c), so the
    # dashboard's vitals stay live without re-polling GET /api/metrics. Like the others it runs
    # for the life of the process and is cancelled on shutdown.
    metrics_tick_task = asyncio.create_task(
        run_metrics_tick(
            app.state.queue,
            app.state.connection_manager,
            interval_seconds=settings.metrics_tick_seconds,
        )
    )
    app.state.metrics_tick_task = metrics_tick_task
    try:
        yield
    finally:
        # Stop the background tasks before closing the clients, so an in-flight sweep, durable
        # write, broadcast, or metrics tick never hits a closed Redis/Postgres client.
        reaper_task.cancel()
        durable_writer_task.cancel()
        broadcaster_task.cancel()
        metrics_tick_task.cancel()
        for background_task in (
            reaper_task,
            durable_writer_task,
            broadcaster_task,
            metrics_tick_task,
        ):
            with suppress(asyncio.CancelledError):
                await background_task
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
app.include_router(realtime.router)
app.include_router(metrics.router)
# Turn guardrail errors (caps, rate limits, full queue) into system-voiced HTTP responses.
# The producer endpoints (POST /api/jobs) are the first to raise them.
register_guardrail_handlers(app)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the process is up. Returns 200 without touching the datastores."""
    return {"status": "ok"}
