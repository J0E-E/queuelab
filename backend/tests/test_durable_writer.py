"""Integration tests for the durable-writer loop (Epic 10a), against real Redis + Postgres.

The durable-writer subscribes to the ``ql:events:state`` channel and copies each job's outcome
onto its durable Postgres row. These tests run the loop as a background task and drive a real
job through claim -> ack (the happy path) and claim -> nack-to-exhaustion (the failure path),
then assert the durable row gained the timing/outcome fields. Pub/sub has no replay, so each
test waits for the subscription to register before driving the job. Mirrors the reaper suite's
``_poll_until`` / running-task helpers.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.models.job import Job
from app.queue.protocol import STATE_CHANNEL, JobState
from app.realtime.durable_writer import run_durable_writer


async def _poll_until[PollResult](
    check: Callable[[], Awaitable[PollResult]], *, attempts: int = 150, interval: float = 0.02
) -> PollResult:
    """Poll ``check`` until it returns a truthy result, then return it; fail if it never does.

    Lets a test wait for the concurrently-running writer to persist an event without a fixed
    sleep that would be flaky.
    """
    for _ in range(attempts):
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met within the poll window")


@contextlib.asynccontextmanager
async def _running_writer(queue, database):
    """Run the durable-writer as a background task for the duration of the block, then cancel it.

    Mirrors the api lifespan's start-task / cancel-and-suppress shutdown.
    """
    task = asyncio.create_task(run_durable_writer(queue, database))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _wait_for_subscriber(redis_client) -> None:
    """Wait until the writer's subscription is live on the state channel.

    Pub/sub has no replay, so a claim/ack published before ``subscribe`` registers would be
    lost and the test would hang. Gating on the server-side subscriber count removes that race.
    """

    async def _subscribed():
        counts = await redis_client.pubsub_numsub(STATE_CHANNEL)
        # pubsub_numsub returns [(channel, count)].
        return bool(counts) and counts[0][1] >= 1

    await _poll_until(_subscribed)


def _seed_job(job_id: uuid.UUID, **overrides) -> Job:
    """Build one durable ``Job`` row sharing ``job_id`` with the Redis hot record."""
    defaults = {
        "id": job_id,
        "session_id": "guest-amber",
        "guest_handle": "guest-amber",
        "type": "email",
        "complexity": 1,
        "max_retries": 2,
        "retry_delay_ms": 50,
        "state": JobState.QUEUED.value,
        "attempts": 0,
        "submitted_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Job(**defaults)


async def _persist_row(database, row: Job) -> None:
    """Write a durable row, as the submission endpoint would have done at submit time."""
    async with database.session() as session:
        session.add(row)
        await session.commit()


async def _get_row(database, job_id: uuid.UUID) -> Job | None:
    """Re-read a durable row in a fresh session, so the writer's commit is visible."""
    async with database.session() as session:
        return await session.get(Job, job_id)


async def test_durable_writer_records_completed_timing(queue, database, redis_client, make_job):
    # Happy path: a real job driven claim -> ack should land started_at, finished_at,
    # duration_ms, worker_id, and the terminal `completed` state on the durable row.
    job_id = uuid.uuid4()
    job = make_job(id=str(job_id), max_retries=2)
    await _persist_row(database, _seed_job(job_id, max_retries=2))
    await queue.enqueue(job)

    async with _running_writer(queue, database):
        await _wait_for_subscriber(redis_client)
        await queue.claim("worker-1", timeout=1)
        await queue.ack(job.id, "worker-1")

        async def _is_finished():
            row = await _get_row(database, job_id)
            return row if row and row.finished_at is not None else None

        row = await _poll_until(_is_finished)

    assert row.state == JobState.COMPLETED.value
    assert row.worker_id == "worker-1"
    assert row.started_at is not None
    assert row.duration_ms is not None
    assert row.duration_ms >= 0


async def test_durable_writer_records_failure_outcome(queue, database, redis_client, make_job):
    # Failure path: a job with no retries left, nacked, goes terminal `failed`. The enriched
    # nack event carries attempts, last_error, and the run timing — all land durably.
    job_id = uuid.uuid4()
    job = make_job(id=str(job_id), max_retries=0)
    await _persist_row(database, _seed_job(job_id, max_retries=0))
    await queue.enqueue(job)

    async with _running_writer(queue, database):
        await _wait_for_subscriber(redis_client)
        await queue.claim("worker-1", timeout=1)
        await queue.nack(job.id, "worker-1", "boom")

        async def _is_failed():
            row = await _get_row(database, job_id)
            return row if row and row.state == JobState.FAILED.value else None

        row = await _poll_until(_is_failed)

    assert row.attempts == 1
    assert row.last_error == "boom"
    assert row.finished_at is not None
    assert row.duration_ms is not None
    assert row.duration_ms >= 0
