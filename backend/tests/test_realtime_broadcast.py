"""Integration test for the real-time broadcaster (Epic 10b, phase 2), against real Redis.

The broadcaster subscribes to ``ql:events:state`` and fans each state change out to every
connected WS /ws client as a ``delta`` frame. This connects a real socket, runs the broadcaster,
drives a job ``claim -> ack``, and asserts the ``running`` then ``completed`` deltas arrive — and
that ``session_id`` never rides along. Mirrors the durable-writer suite's poll / running-task /
wait-for-subscriber helpers (pub/sub has no replay, so the subscription must register first).
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.queue.protocol import STATE_CHANNEL
from app.realtime.broadcaster import run_broadcaster
from httpx_ws import aconnect_ws


async def _poll_until[PollResult](
    check: Callable[[], Awaitable[PollResult]], *, attempts: int = 150, interval: float = 0.02
) -> PollResult:
    """Poll ``check`` until it returns a truthy result, then return it; fail if it never does."""
    for _ in range(attempts):
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met within the poll window")


@contextlib.asynccontextmanager
async def _running_broadcaster(queue, manager):
    """Run the broadcaster as a background task for the duration of the block, then cancel it.

    Mirrors the api lifespan's start-task / cancel-and-suppress shutdown.
    """
    task = asyncio.create_task(run_broadcaster(queue, manager))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _wait_for_subscriber(redis_client) -> None:
    """Wait until the broadcaster's subscription is live on the state channel.

    Pub/sub has no replay, so a claim/ack published before ``subscribe`` registers would be lost
    and the test would hang. Gating on the server-side subscriber count removes that race.
    """

    async def _subscribed():
        counts = await redis_client.pubsub_numsub(STATE_CHANNEL)
        # pubsub_numsub returns [(channel, count)].
        return bool(counts) and counts[0][1] >= 1

    await _poll_until(_subscribed)


async def test_broadcaster_streams_job_deltas(
    queue, connection_manager, ws_app_client, redis_client, make_job
):
    # A single real job, driven claim -> ack, should reach the connected socket as a `running`
    # delta then a `completed` delta. Enqueue itself publishes nothing, so these are the only two.
    job = make_job(payload={"type": "email", "complexity": 1})
    await queue.enqueue(job)

    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        # Drain the snapshot the manager sends on connect, so what follows is purely deltas.
        snapshot = await websocket.receive_json()
        assert snapshot["type"] == "snapshot"

        async with _running_broadcaster(queue, connection_manager):
            await _wait_for_subscriber(redis_client)
            await queue.claim("worker-1", timeout=5)
            await queue.ack(job.id, "worker-1")

            running = await websocket.receive_json()
            completed = await websocket.receive_json()

    assert running["type"] == "delta"
    assert running["event"]["job_id"] == job.id
    assert running["event"]["state"] == "running"
    assert running["event"]["worker_id"] == "worker-1"
    assert "session_id" not in running["event"]

    assert completed["type"] == "delta"
    assert completed["event"]["job_id"] == job.id
    assert completed["event"]["state"] == "completed"
    assert "session_id" not in completed["event"]
