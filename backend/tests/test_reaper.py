"""Integration tests for the reaper loop (Epic 9), against a real Redis.

The reaper adds no queue mechanics — Epic 3's ``reap.lua`` already promotes due delayed
jobs and recovers expired leases, and is tested directly in ``test_queue.py``. These tests
cover the *loop*: that a background sweep, running on its own tick, performs that recovery
on schedule with no manual ``reap()`` call, fails a job past its retry ceiling through the
reap path, and survives a failed sweep. Time is controlled by rewriting the delayed/lease
sorted-set scores into the past (score 0), the same trick the queue tests use — no real
waiting on the 30s timeout.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.queue.protocol import DELAYED_KEY, LEASES_KEY, job_key, processing_key
from app.reaper import run_reaper

ALL_ZERO_COUNTS = {
    "queued": 0,
    "running": 0,
    "completed": 0,
    "failed": 0,
    "retrying": 0,
    "recovered": 0,
}

# A tiny tick so the loop sweeps many times within a sub-second poll window.
FAST_TICK_SECONDS = 0.02


async def _poll_until[PollResult](
    check: Callable[[], Awaitable[PollResult]], *, attempts: int = 150, interval: float = 0.02
) -> PollResult:
    """Poll ``check`` until it returns a truthy result, then return it; fail if it never does.

    Lets a test wait for the concurrently-running reaper loop to recover a job without a
    fixed sleep that would be flaky.
    """
    for _ in range(attempts):
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met within the poll window")


@contextlib.asynccontextmanager
async def _running_reaper(queue, *, interval_seconds: float = FAST_TICK_SECONDS):
    """Run the reaper loop as a background task for the duration of the block, then cancel it.

    Mirrors the api lifespan's start-task / cancel-and-suppress shutdown.
    """
    task = asyncio.create_task(run_reaper(queue, interval_seconds=interval_seconds))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_reaper_promotes_a_due_delayed_job(queue, redis_client, make_job):
    # A nacked job sits in the delayed set as `retrying`; once its backoff is due, the running
    # reaper should move it back to the ready queue with no manual reap call.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-1", timeout=1)
    await queue.nack(job.id, "worker-1", "boom")
    assert await redis_client.hget(job_key(job.id), "state") == "retrying"

    # Force the backoff to have elapsed (due now).
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})

    async def _is_queued():
        return await redis_client.hget(job_key(job.id), "state") == "queued"

    async with _running_reaper(queue):
        await _poll_until(_is_queued)

    assert await queue.queue_depth() == 1
    assert await redis_client.zscore(DELAYED_KEY, job.id) is None
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "queued": 1}


async def test_reaper_requeues_an_expired_lease_job(queue, redis_client, make_job):
    # A worker claims a job then "dies" (lease lapses with no ack/nack). The running reaper
    # should requeue it as `retrying` and clean up the dead worker's in-flight claim.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-A", timeout=1)

    # worker-A's claim deadline (lease) passes.
    await redis_client.zadd(LEASES_KEY, {job.id: 0})

    async def _is_retrying():
        return await redis_client.hget(job_key(job.id), "state") == "retrying"

    async with _running_reaper(queue):
        await _poll_until(_is_retrying)

    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 1
    assert await redis_client.zscore(DELAYED_KEY, job.id) is not None
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.hget(job_key(job.id), "worker_id") is None
    assert await redis_client.lrange(processing_key("worker-A"), 0, -1) == []
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "retrying": 1}


async def test_reaper_fails_a_job_past_its_retry_ceiling(queue, redis_client, make_job):
    # A job with no retries left whose lease lapses goes terminal `failed` through the reaper.
    # This drives reap.lua's failed branch, which is otherwise only reached via nack.
    job = make_job(max_retries=0)
    await queue.enqueue(job)
    await queue.claim("worker-A", timeout=1)

    await redis_client.zadd(LEASES_KEY, {job.id: 0})

    async def _is_failed():
        return await redis_client.hget(job_key(job.id), "state") == "failed"

    async with _running_reaper(queue):
        await _poll_until(_is_failed)

    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 1
    assert await redis_client.zscore(DELAYED_KEY, job.id) is None
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.lrange(processing_key("worker-A"), 0, -1) == []
    # The terminal hot record carries the 1h TTL so it self-cleans.
    assert await redis_client.ttl(job_key(job.id)) > 0
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "failed": 1}


async def test_reaper_survives_a_failed_sweep_and_keeps_ticking(
    queue, redis_client, make_job, monkeypatch
):
    # A transient sweep failure (e.g. a Redis blip) must not stop the loop: the next tick
    # should still recover the job.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-1", timeout=1)
    await queue.nack(job.id, "worker-1", "boom")
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})

    original_reap = queue.reap
    sweep_calls = {"count": 0}

    async def flaky_reap(*args, **kwargs):
        sweep_calls["count"] += 1
        if sweep_calls["count"] == 1:
            raise RuntimeError("transient redis blip")
        return await original_reap(*args, **kwargs)

    monkeypatch.setattr(queue, "reap", flaky_reap)

    async def _is_queued():
        return await redis_client.hget(job_key(job.id), "state") == "queued"

    async with _running_reaper(queue):
        await _poll_until(_is_queued)

    # The first sweep raised, yet the loop kept ticking and a later sweep promoted the job.
    assert sweep_calls["count"] >= 2
    assert await queue.queue_depth() == 1
