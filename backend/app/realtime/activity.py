"""The activity subscriber: fan readable state-change lines out to every WS /ws client (Epic 10d).

The same ``ql:events:state`` pub/sub channel the durable-writer persists and the broadcaster
fans out as raw ``delta`` frames also drives the dashboard's human-readable activity feed. This
module is a third, dedicated subscriber on that channel: for each published state change it formats
a one-line summary (:func:`app.services.activity_feed.format_activity_line`), records it in the
in-memory ring buffer so a late-joiner can be seeded with recent history, and sends it to every
connected browser as an ``{"type": "activity", "line": …}`` frame.

It is the read-many twin of the broadcaster and durable-writer and shares their shape exactly:
one background task, best-effort, cancelled on shutdown, with a re-subscribe-after-a-pause guard
so a transient Redis blip never permanently stops the feed. That shared subscribe loop lives in
:func:`app.realtime.subscriber.run_state_subscriber`; this module supplies only the per-message
handler.
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
from app.services.activity_feed import (
    ActivityFeed,
    build_activity_entry,
    current_time_label,
    format_activity_line,
)
from app.services.session_store import SessionStore

logger = logging.getLogger(__name__)


async def run_activity_feed(
    queue: JobQueue,
    manager: ConnectionManager,
    feed: ActivityFeed,
    session_store: SessionStore,
) -> None:
    """Subscribe to state-change events and fan a readable line out to every connected WS client.

    Runs until the task is cancelled (the api lifespan cancels it on shutdown). The subscribe loop
    and its re-subscribe-after-a-pause guard live in :func:`run_state_subscriber`; handling a
    single event is itself best-effort (see :func:`_handle_message`). The ``session_store`` lets the
    handler attribute each line to the guest who submitted the job (Epic 17b).
    """
    await run_state_subscriber(
        queue,
        STATE_CHANNEL,
        partial(_handle_message, manager, feed, session_store),
        name="activity feed",
    )


async def _handle_message(
    manager: ConnectionManager,
    feed: ActivityFeed,
    session_store: SessionStore,
    message: dict[str, Any],
) -> None:
    """Format one pub/sub message into a line, buffer it, and broadcast it; a bad one is skipped.

    Kept separate from the loop so "one bad event is skipped" stays distinct from "the
    subscription dropped, re-subscribe". A non-:class:`Exception` like ``CancelledError`` is not
    caught here, so a shutdown cancel still propagates up to stop the loop. The line is recorded
    in the ring buffer *before* the broadcast, so it is already part of the recent history any
    client that connects right after this event would be seeded with. The acting guest is resolved
    server-side from the event's ``session_id`` (Epic 17b), so the color attribution can't be
    spoofed and an expired session simply leaves the line unattributed.
    """
    try:
        event = json.loads(message["data"])
        handle, color = await _resolve_actor(session_store, event.get("session_id"))
        entry = build_activity_entry(
            format_activity_line(event), time=current_time_label(), handle=handle, color=color
        )
        feed.record(entry)
        await manager.broadcast({"type": "activity", **entry})
    except Exception:
        logger.exception("activity feed: failed to handle a state event; skipping")


async def _resolve_actor(
    session_store: SessionStore, session_id: str | None
) -> tuple[str | None, str | None]:
    """Resolve a state event's acting guest (the job's submitter) to a ``(handle, color)`` pair.

    Server-side resolution from ``session_id`` (Epic 17b) so the attribution can't be spoofed by a
    client. An absent ``session_id`` or an expired/unknown session resolves to ``(None, None)``,
    leaving the line unattributed (rendered in the neutral system color by the frontend).
    """
    if not session_id:
        return None, None
    identity = await session_store.get_identity(session_id)
    if not identity:
        return None, None
    return identity["handle"], identity["color"]
