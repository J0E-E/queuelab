"""The real-time broadcaster: fan state-change events out to every WS /ws client (Epic 10b).

The same ``ql:events:state`` pub/sub channel the durable-writer persists also drives the live
dashboard. This loop subscribes to that channel and, for each published state change, wraps it
as a ``delta`` frame and hands it to the :class:`ConnectionManager`, which sends it to every
connected browser. It is the read-many twin of the durable-writer's write-one subscriber and
shares its shape exactly: one background task, best-effort, cancelled on shutdown, with a
re-subscribe-after-a-pause guard so a transient Redis blip never permanently stops the feed. That
shared subscribe loop lives in :func:`app.realtime.subscriber.run_state_subscriber`; this module
supplies only the per-message handler.

Each forwarded event drops ``session_id`` first — that id is the rate-limit key the REST layer
never returns, and this view is broadcast to everyone.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Any

from app.queue.client import JobQueue
from app.queue.protocol import STATE_CHANNEL
from app.realtime.connection_manager import ConnectionManager
from app.realtime.subscriber import run_state_subscriber

logger = logging.getLogger(__name__)


async def run_broadcaster(queue: JobQueue, manager: ConnectionManager) -> None:
    """Subscribe to state-change events and fan each out to every connected WS client.

    Runs until the task is cancelled (the api lifespan cancels it on shutdown). The subscribe loop
    and its re-subscribe-after-a-pause guard live in :func:`run_state_subscriber`; forwarding a
    single event is itself best-effort (see :func:`_forward_message`).
    """
    await run_state_subscriber(
        queue, STATE_CHANNEL, partial(_forward_message, manager), name="broadcaster"
    )


async def _forward_message(manager: ConnectionManager, message: dict[str, Any]) -> None:
    """Decode one pub/sub message and broadcast it as a delta; a bad message is logged and skipped.

    Kept separate from the loop so "one bad event is skipped" stays distinct from "the
    subscription dropped, re-subscribe". A non-:class:`Exception` like ``CancelledError`` is not
    caught here, so a shutdown cancel still propagates up to stop the loop.
    """
    try:
        event = json.loads(message["data"])
        event.pop("session_id", None)
        await manager.broadcast({"type": "delta", "event": event})
    except Exception:
        logger.exception("broadcaster: failed to forward a state event; skipping")
