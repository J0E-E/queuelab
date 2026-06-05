"""The metrics tick: push the queue's aggregate vitals over WS /ws on a throttle (Epic 10c).

``GET /api/metrics`` gives a freshly loaded page one read of the queue's vitals; this loop keeps
them live. Every ``interval_seconds`` it computes the same vitals (via
:func:`app.services.metrics.compute_metrics`) and fans them out to every connected client as a
``{"type": "metrics", ...}`` frame. The timer itself is the throttle — the dashboard never
re-polls the REST endpoint.

The loop mirrors the reaper: it sleeps first, the tick is best-effort (a failed compute or
broadcast is logged and the loop carries on, so a transient Redis blip never stops the feed), and
it stops only when the task is cancelled (the api lifespan cancels it on shutdown).
"""

from __future__ import annotations

import asyncio
import logging

from app.queue.client import JobQueue
from app.realtime.connection_manager import ConnectionManager
from app.services.metrics import compute_metrics

logger = logging.getLogger(__name__)


async def run_metrics_tick(
    queue: JobQueue, manager: ConnectionManager, *, interval_seconds: float
) -> None:
    """Broadcast the queue vitals every ``interval_seconds`` until the task is cancelled.

    Each tick computes the live counts plus derived queue depth and worker count, then sends them
    to every connected client as a ``metrics`` frame. The tick is best-effort: a failure is logged
    and the loop carries on to the next tick, so one bad sample never stops the feed.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            metrics = await compute_metrics(queue)
            await manager.broadcast({"type": "metrics", **metrics})
        except Exception:
            logger.exception("metrics tick failed; will retry next tick")
