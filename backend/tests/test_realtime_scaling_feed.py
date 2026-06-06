"""Tests for the scaling feed (Epic 11c): line formatting and the api-side subscriber.

``format_scaling_line`` is pure, so it is unit-tested with plain dicts. The subscriber mirrors the
activity feed's fan-out test: publish a scaling action on the dedicated ``SCALING_CHANNEL`` (as the
autoscaler process would) and assert the readable line reaches a connected WS /ws client as an
``activity`` frame and is buffered for late-joiners. The resilience test drives the handler directly
with no Redis.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from app.queue.protocol import SCALING_CHANNEL
from app.realtime.scaling_feed import _handle_message, run_scaling_feed
from app.services.activity_feed import ActivityFeed, format_scaling_line
from httpx_ws import aconnect_ws

# ---- format_scaling_line (pure) -------------------------------------------------------


def test_scale_up_line_names_the_new_count_and_reason():
    line = format_scaling_line(
        {
            "action": "scale_up",
            "worker_id": None,
            "reason": "queue_depth 12 > threshold 5 → +2",
            "worker_count_after": 2,
        }
    )
    assert line == "scaled up to 2 workers — queue_depth 12 > threshold 5 → +2"


def test_scale_down_line_names_the_new_count():
    line = format_scaling_line(
        {
            "action": "scale_down",
            "worker_id": "worker-1",
            "reason": "queue idle",
            "worker_count_after": 1,
        }
    )
    assert line == "scaled down to 1 worker — queue idle"


def test_replace_line_names_the_worker():
    line = format_scaling_line(
        {
            "action": "replace",
            "worker_id": "worker-stale",
            "reason": "heartbeat stale",
            "worker_count_after": 1,
        }
    )
    assert line == "replaced worker-stale — heartbeat stale"


def test_unknown_action_still_yields_a_sensible_line():
    # Nothing is ever dropped — an unrecognized action falls back to a plain label.
    assert format_scaling_line({"action": "destroy", "reason": "chaos"}) == "destroy — chaos"
    assert format_scaling_line({}) == "scaling"


# ---- The subscriber (real Redis) ------------------------------------------------------


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
async def _running_scaling_feed(queue, manager, feed):
    """Run the scaling subscriber as a background task for the block, then cancel it."""
    task = asyncio.create_task(run_scaling_feed(queue, manager, feed))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _wait_for_subscriber(redis_client) -> None:
    """Wait until the subscription is live on the scaling channel (pub/sub has no replay)."""

    async def _subscribed():
        counts = await redis_client.pubsub_numsub(SCALING_CHANNEL)
        return bool(counts) and counts[0][1] >= 1

    await _poll_until(_subscribed)


async def test_scaling_feed_streams_a_readable_line(
    queue, connection_manager, activity_feed, ws_app_client, redis_client
):
    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        # Drain the connect snapshot, so what follows is purely the scaling line.
        snapshot = await websocket.receive_json()
        assert snapshot["type"] == "snapshot"

        async with _running_scaling_feed(queue, connection_manager, activity_feed):
            await _wait_for_subscriber(redis_client)
            await queue.publish_scaling_event(
                {
                    "action": "scale_up",
                    "worker_id": None,
                    "reason": "queue_depth 12 > threshold 5 → +2",
                    "worker_count_after": 2,
                }
            )
            frame = await websocket.receive_json()

    assert frame["type"] == "activity"
    assert frame["line"] == "scaled up to 2 workers — queue_depth 12 > threshold 5 → +2"
    # The same line was buffered, so a client connecting now would be seeded with it.
    assert activity_feed.recent() == ["scaled up to 2 workers — queue_depth 12 > threshold 5 → +2"]


class _RecordingManager:
    """A stand-in connection manager that just records what it was asked to broadcast."""

    def __init__(self) -> None:
        self.broadcasts: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.broadcasts.append(message)


async def test_handle_message_skips_a_malformed_event():
    # A message whose data is not valid JSON must be swallowed: nothing buffered, nothing
    # broadcast, no exception — that is what keeps the shared subscribe loop alive across a bad one.
    manager = _RecordingManager()
    feed = ActivityFeed(max_lines=5)

    await _handle_message(manager, feed, {"type": "message", "data": "not-json{"})

    assert feed.recent() == []
    assert manager.broadcasts == []
