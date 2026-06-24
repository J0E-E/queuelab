"""Integration test for the worker claim loop (Epic 8b).

Drives the real :func:`worker.run_worker` against a real Redis (testcontainers): it enqueues
a batch through the genuine backend queue, runs the worker until the batch drains, then
asserts the jobs reached the right terminal state, the live counts moved, and nothing is left
in flight. Randomness is injected via a small ``FixedRandom`` stub so each job's pass/fail
outcome is deterministic — no flakiness. Requires a Docker daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.queue.protocol import DELAYED_KEY, LEASES_KEY, job_key, processing_key

from worker import run_worker

# A draw of 1.0 is >= any failure probability, so the simulated job always succeeds; a draw
# of 0.0 is below any non-zero probability, so it always fails.
ALWAYS_SUCCEEDS_DRAW = 1.0
ALWAYS_FAILS_DRAW = 0.0


async def _poll_until[PollResult](
    check: Callable[[], Awaitable[PollResult]], *, attempts: int = 150, interval: float = 0.02
) -> PollResult:
    """Poll ``check`` until it returns a truthy result, then return it; fail if it never does.

    Lets a test wait for the concurrently-running worker to reach a state (registered, a job
    claimed, the heartbeat advanced) without a fixed sleep that would be flaky.
    """
    for _ in range(attempts):
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met within the poll window")


class FixedRandom:
    """A drop-in for ``random.Random`` that returns preset values (deterministic outcomes).

    ``random`` always returns ``draw_value`` (the pass/fail draw) and ``uniform`` always
    returns ``jitter_value`` (the duration jitter factor), so the worker's outcome and sleep
    are both pinned.
    """

    def __init__(self, *, draw_value: float, jitter_value: float = 1.0) -> None:
        self.draw_value = draw_value
        self.jitter_value = jitter_value

    def uniform(self, low: float, high: float) -> float:
        return self.jitter_value

    def random(self) -> float:
        return self.draw_value


async def test_worker_drains_a_batch_to_completed(queue, redis_client, make_job):
    """A worker claims and acks every job in a batch; counts move queued -> running -> completed."""
    worker_id = "worker-test"
    batch = [make_job() for _ in range(4)]
    for job in batch:
        await queue.enqueue(job)
    assert await queue.queue_depth() == 4

    always_succeeds = FixedRandom(draw_value=ALWAYS_SUCCEEDS_DRAW)
    await run_worker(queue, worker_id, poll_timeout=0.2, max_idle_polls=1, rng=always_succeeds)

    assert await queue.counts() == {
        "queued": 0,
        "running": 0,
        "completed": 4,
        "failed": 0,
        "retrying": 0,
    }
    for job in batch:
        assert await redis_client.hget(job_key(job.id), "state") == "completed"
    # Nothing left in flight: the lease set is empty and the processing list is drained.
    assert await redis_client.zcard(LEASES_KEY) == 0
    assert await redis_client.lrange(processing_key(worker_id), 0, -1) == []


async def test_worker_marks_a_failing_job_failed_when_retries_exhausted(
    queue, redis_client, make_job
):
    """With no retries left, a failed job goes terminally ``failed`` rather than ``retrying``."""
    worker_id = "worker-test"
    batch = [make_job(max_retries=0) for _ in range(3)]
    for job in batch:
        await queue.enqueue(job)

    always_fails = FixedRandom(draw_value=ALWAYS_FAILS_DRAW)
    await run_worker(queue, worker_id, poll_timeout=0.2, max_idle_polls=1, rng=always_fails)

    assert await queue.counts() == {
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 3,
        "retrying": 0,
    }
    for job in batch:
        assert await redis_client.hget(job_key(job.id), "state") == "failed"
    assert await redis_client.zcard(LEASES_KEY) == 0
    assert await redis_client.lrange(processing_key(worker_id), 0, -1) == []


async def test_injected_failure_bias_forces_an_otherwise_passing_job_to_fail(
    queue, redis_client, make_job
):
    """A live chaos failure-bias pushes a would-pass job (draw 0.5 ≥ base rate) to ``failed``."""
    worker_id = "worker-test"
    # A full bias clamps every job's failure probability to 1.0, so even a mid-range pass/fail
    # draw (which clears the ~2-25% base rates) now fails.
    await queue.set_failure_bias(1.0, ttl_seconds=30)
    batch = [make_job(max_retries=0) for _ in range(3)]
    for job in batch:
        await queue.enqueue(job)

    would_pass_unbiased = FixedRandom(draw_value=0.5)
    await run_worker(queue, worker_id, poll_timeout=0.2, max_idle_polls=1, rng=would_pass_unbiased)

    assert (await queue.counts())["failed"] == 3
    for job in batch:
        assert await redis_client.hget(job_key(job.id), "state") == "failed"


async def test_worker_survives_a_malformed_job(queue, redis_client, make_job):
    """An unrunnable job is nacked, not crashed on; the worker keeps draining the rest."""
    worker_id = "worker-test"
    # An unknown job type makes simulate raise — the kind of bad record that must not take
    # the worker down. With no retries left it settles terminally ``failed``.
    malformed = make_job(max_retries=0, payload={"type": "bogus", "complexity": 1})
    healthy = make_job()
    await queue.enqueue(malformed)
    await queue.enqueue(healthy)

    always_succeeds = FixedRandom(draw_value=ALWAYS_SUCCEEDS_DRAW)
    await run_worker(queue, worker_id, poll_timeout=0.2, max_idle_polls=1, rng=always_succeeds)

    # The bad job failed without crashing the loop, and the good job after it still completed.
    assert await redis_client.hget(job_key(malformed.id), "state") == "failed"
    assert await redis_client.hget(job_key(healthy.id), "state") == "completed"
    assert await redis_client.zcard(LEASES_KEY) == 0
    assert await redis_client.lrange(processing_key(worker_id), 0, -1) == []


async def test_worker_renews_the_lease_on_a_long_running_job(
    queue, redis_client, make_job, monkeypatch
):
    """A job that outlasts the renewal interval gets its lease re-stamped while it runs."""
    worker_id = "worker-test"
    job = make_job()
    await queue.enqueue(job)

    renewals: list[str] = []
    original_renew_lease = queue.renew_lease

    async def _counting_renew_lease(job_id: str, claiming_worker_id: str) -> None:
        renewals.append(job_id)
        await original_renew_lease(job_id, claiming_worker_id)

    monkeypatch.setattr(queue, "renew_lease", _counting_renew_lease)

    # jitter 3.0 stretches the email/complexity-1 job to ~900ms; renewing every 50ms means
    # several renewals fire before it finishes — a long-but-alive job holds its claim.
    long_running = FixedRandom(draw_value=ALWAYS_SUCCEEDS_DRAW, jitter_value=3.0)
    await run_worker(
        queue,
        worker_id,
        poll_timeout=0.2,
        max_idle_polls=1,
        rng=long_running,
        lease_renewal_seconds=0.05,
    )

    # The lease was renewed at least once, only ever for the running job, and it still completed.
    assert len(renewals) >= 1
    assert set(renewals) == {job.id}
    assert await redis_client.hget(job_key(job.id), "state") == "completed"


async def test_worker_completes_job_even_when_lease_renewal_fails(
    queue, redis_client, make_job, monkeypatch
):
    """A failing lease renewal is swallowed; the job still settles on its real outcome."""
    worker_id = "worker-test"
    job = make_job()
    await queue.enqueue(job)

    async def _failing_renew_lease(job_id: str, claiming_worker_id: str) -> None:
        raise RuntimeError("simulated redis blip during renewal")

    monkeypatch.setattr(queue, "renew_lease", _failing_renew_lease)

    # The email job runs ~300ms; renewing every 50ms means the failing renew is hit several
    # times — best-effort, so it must not abort the job that otherwise succeeds.
    succeeds = FixedRandom(draw_value=ALWAYS_SUCCEEDS_DRAW)
    await run_worker(
        queue,
        worker_id,
        poll_timeout=0.2,
        max_idle_polls=1,
        rng=succeeds,
        lease_renewal_seconds=0.05,
    )

    # The renew kept failing, but the successful job still completed (not nacked / failed).
    assert await redis_client.hget(job_key(job.id), "state") == "completed"
    assert await redis_client.zcard(LEASES_KEY) == 0
    assert await redis_client.lrange(processing_key(worker_id), 0, -1) == []


async def test_worker_registers_and_refreshes_its_heartbeat(queue, redis_client):
    """The worker appears in ql:workers, refreshes its heartbeat, and deregisters on exit."""
    worker_id = "worker-test"
    stop_event = asyncio.Event()

    async def _worker_record():
        return (await queue.list_workers()).get(worker_id)

    # Run the worker with nothing to claim; it should still register and keep heartbeating.
    worker_task = asyncio.create_task(
        run_worker(
            queue,
            worker_id,
            poll_timeout=0.05,
            stop_event=stop_event,
            heartbeat_seconds=0.05,
        )
    )
    try:
        # It registers up front as idle, with no current job.
        registered = await _poll_until(_worker_record)
        assert registered["state"] == "idle"
        assert registered["current_job"] is None
        first_heartbeat = registered["last_heartbeat"]

        # The heartbeat keeps refreshing while the worker runs.
        async def _heartbeat_advanced():
            record = await _worker_record()
            if record is not None and record["last_heartbeat"] > first_heartbeat:
                return record
            return None

        await _poll_until(_heartbeat_advanced)
    finally:
        stop_event.set()
        await worker_task

    # A cleanly stopped worker removes itself from the registry.
    assert await queue.list_workers() == {}


async def test_graceful_shutdown_requeues_the_in_flight_job(queue, redis_client, make_job):
    """A graceful stop hands the in-flight job back to ready as `queued`, no retry consumed."""
    worker_id = "worker-test"
    job = make_job(max_retries=2)
    await queue.enqueue(job)

    stop_event = asyncio.Event()
    # jitter 3.0 stretches the email/complexity-1 job to ~900ms, so there is a comfortable
    # window to stop the worker while the job is still mid-flight.
    long_running = FixedRandom(draw_value=ALWAYS_SUCCEEDS_DRAW, jitter_value=3.0)
    worker_task = asyncio.create_task(
        run_worker(
            queue,
            worker_id,
            poll_timeout=0.05,
            rng=long_running,
            lease_renewal_seconds=0.05,
            stop_event=stop_event,
            heartbeat_seconds=0.05,
        )
    )
    try:
        # Wait until the job is actually claimed and running, then ask the worker to stop.
        async def _job_is_running():
            return (await queue.counts())["running"] == 1

        await _poll_until(_job_is_running)
        stop_event.set()
        await worker_task
    finally:
        if not worker_task.done():
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

    # The in-flight job is back on the ready queue as `queued`, owner cleared, no retry burned.
    assert await queue.queue_depth() == 1
    assert await redis_client.hget(job_key(job.id), "state") == "queued"
    assert await redis_client.hget(job_key(job.id), "worker_id") is None
    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 0
    # The in-flight claim is gone and it never went onto the delayed (retry) set.
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.zscore(DELAYED_KEY, job.id) is None
    assert await redis_client.lrange(processing_key(worker_id), 0, -1) == []
    assert await queue.counts() == {
        "queued": 1,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "retrying": 0,
    }
    # The worker deregistered on its way out.
    assert await queue.list_workers() == {}
