"""The reaper: a periodic best-effort recovery sweep run inside the api process (Epic 9).

Epic 3 built the atomic recovery sweep (``reap.lua`` / :meth:`JobQueue.reap`) but nothing
calls it on a schedule, so at runtime a delayed (retrying) job never promotes back to the
ready queue and a dead worker's leased job never gets requeued. This loop closes that gap:
every ``interval_seconds`` it runs one sweep, which promotes due delayed jobs to the ready
queue and requeues jobs whose claim deadline (lease) lapsed — recovering them as
``retrying`` (or terminal ``failed`` once their retries are exhausted). It is what makes
"destroy a worker -> its job is retried" and "a nacked job comes back after its backoff"
true at runtime.

The loop mirrors the worker's heartbeat task: it sleeps first, the sweep is best-effort (a
failed sweep is logged and the loop carries on, so a transient Redis blip never stops
recovery), and it stops only when the task is cancelled (the api lifespan cancels it on
shutdown).
"""

from __future__ import annotations

import asyncio
import logging

from app.queue.client import JobQueue

logger = logging.getLogger(__name__)


async def run_reaper(queue: JobQueue, *, interval_seconds: float) -> None:
    """Run one recovery sweep every ``interval_seconds`` until the task is cancelled.

    Each sweep promotes due delayed jobs to the ready queue and requeues jobs whose lease
    lapsed. The sweep is best-effort: a failure is logged and the loop carries on to the
    next tick, so a transient Redis error never stops recovery.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            promoted, recovered = await queue.reap()
        except Exception:
            logger.exception("reaper sweep failed; will retry next tick")
            continue
        if promoted or recovered:
            logger.info(
                "reaper: promoted %d delayed job(s), recovered %d expired lease(s)",
                promoted,
                recovered,
            )
