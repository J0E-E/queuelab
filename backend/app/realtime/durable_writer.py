"""The durable-writer: a background subscriber that copies job outcomes into Postgres (Epic 10a).

The Redis hot record (the ``ql:job:{id}`` hash) ages out an hour after a job finishes, so the
durable Postgres ``Job`` row must capture the outcome before that TTL lapses. This loop
subscribes to the ``ql:events:state`` pub/sub channel and, for each state-change event, writes
the timing/outcome fields (``state``, ``worker_id``, ``started_at``, ``finished_at``,
``duration_ms``, ``attempts``, ``last_error``) onto the matching durable row by id.

It mirrors the reaper's lifespan task — one background task, best-effort, cancelled on
shutdown — but the loop shape differs. The reaper *sleeps then sweeps* on a tick; this loop
*blocks on the pub/sub stream* and reacts to each published event. Two layers of best-effort
keep it alive: a single malformed event or missing row is logged and skipped (the run carries
on to the next event), and a dropped subscription (a transient Redis blip) is logged and
re-subscribed after a short pause — so neither a bad message nor a Redis hiccup ever
permanently stops the writer. It stops only when the task is cancelled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from app.db.engine import Database
from app.models.job import Job
from app.queue.client import JobQueue
from app.queue.protocol import STATE_CHANNEL

logger = logging.getLogger(__name__)

# How long to wait before re-subscribing after the subscription drops, so a transient Redis
# outage retries calmly instead of spinning. Mirrors the reaper's "log and carry on" posture.
RESUBSCRIBE_DELAY_SECONDS = 1.0


async def run_durable_writer(queue: JobQueue, database: Database) -> None:
    """Subscribe to state-change events and persist each onto its durable job row.

    Runs until the task is cancelled (the api lifespan cancels it on shutdown). If the
    subscription drops, it logs and re-subscribes after :data:`RESUBSCRIBE_DELAY_SECONDS`;
    persisting a single event is itself best-effort (see :func:`_handle_message`).
    """
    while True:
        pubsub = queue.pubsub()
        try:
            await pubsub.subscribe(STATE_CHANNEL)
            async for message in pubsub.listen():
                # listen() also yields the subscribe-confirmation frame; act only on messages.
                if message.get("type") != "message":
                    continue
                await _handle_message(database, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "durable-writer: subscription dropped; re-subscribing in %ss",
                RESUBSCRIBE_DELAY_SECONDS,
            )
            await asyncio.sleep(RESUBSCRIBE_DELAY_SECONDS)
        finally:
            # Return the connection to the pool; best-effort so a closing error never masks the
            # cancellation (or the drop) that unwound us here.
            with suppress(Exception):
                await pubsub.aclose()


async def _handle_message(database: Database, message: dict[str, Any]) -> None:
    """Decode one pub/sub message and persist it; a bad message is logged and skipped.

    Kept separate from the loop so "one bad event is skipped" stays distinct from "the
    subscription dropped, re-subscribe". A non-:class:`Exception` like ``CancelledError`` is
    not caught here, so a shutdown cancel still propagates up to stop the loop.
    """
    try:
        event = json.loads(message["data"])
        await _persist_event(database, event)
    except Exception:
        logger.exception("durable-writer: failed to persist a state event; skipping")


async def _persist_event(database: Database, event: dict[str, Any]) -> None:
    """Write one state-change event's fields onto the durable ``Job`` row it names.

    Each event carries only the fields relevant to its transition, so the update is applied
    field-by-field on whatever the event provides; ``state`` is always present. ``duration_ms``
    is computed from the event's own epoch pair (finish minus start), so it never depends on
    having seen an earlier event — making re-delivery and out-of-order events harmless.

    ``state`` itself, by contrast, is last-write-wins: it stays correct only because every event
    for a job arrives in publish order on the single ``ql:events:state`` channel. ``duration_ms``
    is the one field made truly independent of delivery order.
    """
    job_id = uuid.UUID(event["job_id"])
    async with database.session() as session:
        job = await session.get(Job, job_id)
        if job is None:
            # The submission endpoint always writes the row first, so a missing row means a
            # replay or an out-of-band id — there is nothing to update.
            logger.warning("durable-writer: no durable row for job %s; skipping", job_id)
            return

        job.state = event["state"]
        if "worker_id" in event:
            job.worker_id = event["worker_id"]
        if "attempts" in event:
            job.attempts = event["attempts"]
        if "last_error" in event:
            job.last_error = event["last_error"]
        if "started_at" in event:
            job.started_at = _milliseconds_to_datetime(event["started_at"])

        # The ack event names the finish moment as ``completed_at``; the enriched fail events
        # name it ``finished_at``. Treat either as the finish time, and pair it with the run's
        # start to record how long the job ran.
        finished_at_ms = event.get("completed_at", event.get("finished_at"))
        if finished_at_ms is not None:
            job.finished_at = _milliseconds_to_datetime(finished_at_ms)
            if "started_at" in event:
                job.duration_ms = finished_at_ms - event["started_at"]

        await session.commit()


def _milliseconds_to_datetime(epoch_milliseconds: int) -> datetime:
    """Convert an epoch-millisecond timestamp (the queue's clock unit) to a tz-aware datetime."""
    return datetime.fromtimestamp(epoch_milliseconds / 1000, tz=UTC)
