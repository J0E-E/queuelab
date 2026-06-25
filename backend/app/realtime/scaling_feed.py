"""The scaling-feed subscriber: fan autoscaler actions onto the activity feed (Epic 11c).

The autoscaler runs in its own process and publishes each action on the ``ql:events:scaling``
pub/sub channel (a dedicated channel, separate from the job-state channel the broadcaster and
durable-writer watch). This module is a subscriber on that channel for the api process: for each
published action it formats a one-line summary
(:func:`app.services.activity_feed.format_scaling_line`), records it in the in-memory ring buffer
so a late-joiner can be seeded with it, and sends it to every connected browser as an
``{"type": "activity", "line": …}`` frame — the same frame shape the job activity feed uses, so a
scaling line and a job line sit side by side in one feed.

It shares the activity feed's exact shape: one background task, best-effort, cancelled on shutdown,
with a re-subscribe-after-a-pause guard so a transient Redis blip never permanently stops the feed.
That shared subscribe loop lives in :func:`app.realtime.subscriber.run_state_subscriber`; this
module supplies only the per-message handler.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Any

from app.queue.client import JobQueue
from app.queue.protocol import SCALING_CHANNEL
from app.realtime.connection_manager import ConnectionManager
from app.realtime.subscriber import run_state_subscriber
from app.services.activity_feed import (
    ActivityFeed,
    build_activity_entry,
    current_time_label,
    format_scaling_line,
)

logger = logging.getLogger(__name__)


async def run_scaling_feed(queue: JobQueue, manager: ConnectionManager, feed: ActivityFeed) -> None:
    """Subscribe to autoscaler actions and fan a readable line out to every connected WS client.

    Runs until the task is cancelled (the api lifespan cancels it on shutdown). The subscribe loop
    and its re-subscribe-after-a-pause guard live in :func:`run_state_subscriber`; handling a
    single action is itself best-effort (see :func:`_handle_message`).
    """
    await run_state_subscriber(
        queue, SCALING_CHANNEL, partial(_handle_message, manager, feed), name="scaling feed"
    )


async def _handle_message(
    manager: ConnectionManager, feed: ActivityFeed, message: dict[str, Any]
) -> None:
    """Format one scaling action into a line, buffer it, and broadcast it; a bad one is skipped.

    Kept separate from the loop so "one bad event is skipped" stays distinct from "the
    subscription dropped, re-subscribe". A non-:class:`Exception` like ``CancelledError`` is not
    caught here, so a shutdown cancel still propagates up to stop the loop. The line is recorded in
    the ring buffer *before* the broadcast, so it is already part of the recent history any client
    that connects right after this action would be seeded with.
    """
    try:
        event = json.loads(message["data"])
        # The autoscaler stamps the acting actor onto the event (Epic 17b): the triggering guest's
        # handle + color for a chaos destroy, or its own ``autoscaler`` identity for an automatic
        # scale. We render whatever it sent; an older event without them stays unattributed.
        entry = build_activity_entry(
            format_scaling_line(event),
            time=current_time_label(),
            handle=event.get("handle"),
            color=event.get("color"),
        )
        feed.record(entry)
        await manager.broadcast({"type": "activity", **entry})
    except Exception:
        logger.exception("scaling feed: failed to handle a scaling event; skipping")
