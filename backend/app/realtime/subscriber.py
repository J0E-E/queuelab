"""The shared state-channel subscribe loop behind every real-time subscriber (Epic 10d).

The broadcaster (Epic 10b), durable-writer (Epic 10a), and activity feed (Epic 10d) are the same
shape: subscribe to ``ql:events:state``, react to each published message, and survive both a
single bad message and a dropped subscription. That common skeleton lives here — subscribe,
re-subscribe-after-a-pause on a drop, and return the connection on the way out — so each
subscriber is now just its own per-message handler. One loop, three callers.

A single malformed message is the *handler's* concern, not this loop's: each ``handle_message`` is
best-effort and swallows its own per-message errors, so one bad event never unwinds the loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from app.queue.client import JobQueue

logger = logging.getLogger(__name__)

# How long to wait before re-subscribing after the subscription drops, so a transient Redis
# outage retries calmly instead of spinning.
RESUBSCRIBE_DELAY_SECONDS = 1.0


async def run_state_subscriber(
    queue: JobQueue,
    channel: str,
    handle_message: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    name: str,
) -> None:
    """Subscribe to ``channel`` and pass each published message to ``handle_message``.

    Runs until the task is cancelled (the api lifespan cancels every subscriber on shutdown). If
    the subscription drops it logs and re-subscribes after :data:`RESUBSCRIBE_DELAY_SECONDS`;
    ``name`` only labels that log line so each caller's drops stay distinguishable. Handling a
    single message is the caller's concern — ``handle_message`` is expected to be best-effort, so a
    non-:class:`Exception` like ``CancelledError`` still propagates up here to stop the loop.
    """
    while True:
        pubsub = queue.pubsub()
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                # listen() also yields the subscribe-confirmation frame; act only on messages.
                if message.get("type") != "message":
                    continue
                await handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "%s: subscription dropped; re-subscribing in %ss",
                name,
                RESUBSCRIBE_DELAY_SECONDS,
            )
            await asyncio.sleep(RESUBSCRIBE_DELAY_SECONDS)
        finally:
            # Return the connection to the pool; best-effort so a closing error never masks the
            # cancellation (or the drop) that unwound us here.
            with suppress(Exception):
                await pubsub.aclose()
