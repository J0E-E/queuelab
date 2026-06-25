"""Integration test for the throttled metrics tick (Epic 10c, phase 2), against real Redis.

The metrics tick pushes the queue's aggregate vitals — counts plus derived queue depth and
worker count — to every connected WS /ws client every ``metrics_tick_seconds``. This connects a
real socket, runs the tick on a fast interval, and asserts a ``metrics`` frame arrives matching
the live counts. Unlike the broadcaster it rides no pub/sub, so there is no subscriber to wait
for — it is a pure timer.
"""

import asyncio
import contextlib

from app.realtime.metrics_tick import run_metrics_tick
from httpx_ws import aconnect_ws

# A fast tick so the test sees a frame promptly without waiting the 1s production interval.
FAST_TICK_SECONDS = 0.02


@contextlib.asynccontextmanager
async def _running_metrics_tick(queue, manager, *, interval_seconds=FAST_TICK_SECONDS):
    """Run the metrics tick as a background task for the duration of the block, then cancel it.

    Mirrors the api lifespan's start-task / cancel-and-suppress shutdown.
    """
    task = asyncio.create_task(run_metrics_tick(queue, manager, interval_seconds=interval_seconds))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_metrics_tick_broadcasts_vitals(queue, connection_manager, ws_app_client, make_job):
    # Two jobs enqueued, one claimed (queued -> running), one registered worker, so the tick has
    # non-trivial vitals to report.
    first = make_job(payload={"type": "email", "complexity": 1})
    second = make_job(payload={"type": "report", "complexity": 3})
    await queue.enqueue(first)
    await queue.enqueue(second)
    await queue.claim("worker-1", timeout=5)
    await queue.heartbeat("worker-1", state="busy", current_job=first.id)

    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        # Drain the snapshot the manager sends on connect, so the next frame is a metrics tick.
        snapshot = await websocket.receive_json()
        assert snapshot["type"] == "snapshot"

        async with _running_metrics_tick(queue, connection_manager):
            metrics = await websocket.receive_json()

    assert metrics["type"] == "metrics"
    assert metrics["counts"] == await queue.counts()
    assert metrics["counts"]["queued"] == 1
    assert metrics["counts"]["running"] == 1
    assert metrics["queue_depth"] == 1
    assert metrics["worker_count"] == 1
    assert metrics["unhealthy_worker_count"] == 0
    assert metrics["workers"] == [{"id": "worker-1", "healthy": True, "busy": True}]
