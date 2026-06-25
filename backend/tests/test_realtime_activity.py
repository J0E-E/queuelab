"""Integration tests for the activity feed (Epic 10d), against real Redis.

Three behaviors, mirroring the broadcaster and snapshot suites:

- **Fan-out** — the activity subscriber turns each state change into a readable line and sends it
  to every connected WS /ws client as an ``activity`` frame. This connects a real socket, runs the
  subscriber, drives a job ``claim -> ack``, and asserts the two readable lines arrive — and that
  ``session_id`` never leaks into one.
- **Connect-time seeding** — a freshly-connected client's opening ``snapshot`` already carries the
  recent activity lines, so a late-joiner sees recent history without waiting for the next change.
- **Resilience** — one malformed event is swallowed by the per-message handler (buffering nothing,
  broadcasting nothing) rather than raising, so the shared subscribe loop survives a bad message.
  This one needs no Redis: it drives :func:`_handle_message` directly with a fake manager.

The poll / running-task / wait-for-subscriber helpers are local copies of the broadcaster suite's
(pub/sub has no replay, so the subscription must register before the claim/ack is published).
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from app.queue.protocol import STATE_CHANNEL
from app.realtime.activity import _handle_message, run_activity_feed
from app.services.activity_feed import (
    ActivityFeed,
    build_activity_entry,
    format_activity_line,
)
from app.services.identity import GuestIdentity
from httpx_ws import aconnect_ws


class _NoSessions:
    """A session store that knows no sessions — every line resolves as unattributed.

    Lets the Redis-free handler tests run without a real store; resolution short-circuits to
    ``(None, None)`` exactly as an expired/unknown session would.
    """

    async def get_identity(self, session_id: str) -> None:
        return None


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
async def _running_activity_feed(queue, manager, feed, session_store):
    """Run the activity subscriber as a background task for the block, then cancel it.

    Mirrors the api lifespan's start-task / cancel-and-suppress shutdown.
    """
    task = asyncio.create_task(run_activity_feed(queue, manager, feed, session_store))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _wait_for_subscriber(redis_client) -> None:
    """Wait until the subscriber's subscription is live on the state channel.

    Pub/sub has no replay, so a claim/ack published before ``subscribe`` registers would be lost
    and the test would hang. Gating on the server-side subscriber count removes that race.
    """

    async def _subscribed():
        counts = await redis_client.pubsub_numsub(STATE_CHANNEL)
        # pubsub_numsub returns [(channel, count)].
        return bool(counts) and counts[0][1] >= 1

    await _poll_until(_subscribed)


async def test_activity_feed_streams_readable_lines(
    queue, connection_manager, activity_feed, session_store, ws_app_client, redis_client, make_job
):
    # A single real job, driven claim -> ack, should reach the connected socket as a readable
    # `started` line then a `finished` line. Enqueue publishes nothing, so these are the only two.
    # The job's session is unknown to the store, so the lines stay unattributed (handle/color None).
    job = make_job(payload={"type": "email", "complexity": 1})
    await queue.enqueue(job)

    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        # Drain the snapshot the manager sends on connect, so what follows is purely activity.
        snapshot = await websocket.receive_json()
        assert snapshot["type"] == "snapshot"

        async with _running_activity_feed(queue, connection_manager, activity_feed, session_store):
            await _wait_for_subscriber(redis_client)
            await queue.claim("worker-1", timeout=5)
            await queue.ack(job.id, "worker-1")

            started = await websocket.receive_json()
            finished = await websocket.receive_json()

    assert started["type"] == "activity"
    assert started["line"] == f"worker-1 started {job.id}"
    assert started["handle"] is None
    assert "guest-amber" not in started["line"]

    assert finished["type"] == "activity"
    assert finished["line"] == f"worker-1 finished {job.id}"
    assert "guest-amber" not in finished["line"]

    # The same lines were buffered as structured entries, so a client connecting now would be
    # seeded with them (oldest first).
    assert [entry["line"] for entry in activity_feed.recent()] == [
        f"worker-1 started {job.id}",
        f"worker-1 finished {job.id}",
    ]


async def test_activity_line_is_attributed_to_the_submitting_guest(
    queue, connection_manager, activity_feed, session_store, ws_app_client, redis_client, make_job
):
    # A line is attributed to the guest who submitted the job, resolved server-side from the
    # event's session_id (Epic 17b): the frame carries that guest's handle + color, and the flat
    # line leads with the handle so a screen reader hears who acted.
    await session_store.save(
        GuestIdentity(session_id="sess-teal", guest_handle="guest-teal", color="#2dd4bf")
    )
    job = make_job(session_id="sess-teal", payload={"type": "email", "complexity": 1})
    await queue.enqueue(job)

    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        snapshot = await websocket.receive_json()
        assert snapshot["type"] == "snapshot"

        async with _running_activity_feed(queue, connection_manager, activity_feed, session_store):
            await _wait_for_subscriber(redis_client)
            await queue.claim("worker-1", timeout=5)
            started = await websocket.receive_json()

    assert started["handle"] == "guest-teal"
    assert started["color"] == "#2dd4bf"
    assert started["line"] == f"guest-teal worker-1 started {job.id}"


async def test_snapshot_seeds_recent_activity_on_connect(
    connection_manager, activity_feed, ws_app_client
):
    # Pre-load a couple of structured entries, as the running subscriber would have, then connect.
    started = build_activity_entry(
        format_activity_line({"job_id": "job-1", "state": "running", "worker_id": "worker-1"}),
        time="00:00:01",
    )
    finished = build_activity_entry(
        format_activity_line({"job_id": "job-1", "state": "completed", "worker_id": "worker-1"}),
        time="00:00:02",
    )
    activity_feed.record(started)
    activity_feed.record(finished)

    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        snapshot = await websocket.receive_json()

    assert snapshot["type"] == "snapshot"
    # The recent entries ride the opening snapshot, oldest first — a late-joiner sees the same
    # colored, attributed history the live stream carries.
    assert snapshot["activity"] == [started, finished]


class _RecordingManager:
    """A stand-in connection manager that just records what it was asked to broadcast."""

    def __init__(self) -> None:
        self.broadcasts: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.broadcasts.append(message)


async def test_handle_message_skips_a_malformed_event():
    # A message whose data is not valid JSON must be swallowed by the handler: nothing buffered,
    # nothing broadcast, and crucially no exception — that is what keeps the shared subscribe loop
    # alive across a single bad event.
    manager = _RecordingManager()
    feed = ActivityFeed(max_lines=5)

    await _handle_message(manager, feed, _NoSessions(), {"type": "message", "data": "not-json{"})

    assert feed.recent() == []
    assert manager.broadcasts == []
