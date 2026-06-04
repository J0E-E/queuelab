"""QueueLab worker — the consumer side of the core flow (Epic 8b).

A real worker process: it claims a job from the custom Redis queue, runs it through the
simulated work profile (Epic 8a's :mod:`simulate`), and acknowledges success (``ack``) or
failure (``nack``). Each cycle handles one job — claim, run, settle — so a submitted batch
genuinely drains.

The queue mechanics are real: ``claim`` is an all-at-once or not-at-all (atomic) blocking
grab-and-move, leases are real, and a failed job either retries with backoff or goes
terminally ``failed``. Only the work each job performs is simulated.

Graceful SIGTERM shutdown (cleanly returning an in-flight job) and ``ql:workers``
registration arrive in Epic 8c; a hard kill is recovered by the lease-expiry reaper
(Epic 9). Here the loop's only finiteness is the finite per-claim poll timeout, plus an
optional ``max_idle_polls`` the integration test uses to stop once a batch has drained.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import socket

from app.config import settings
from app.queue.client import JobQueue
from app.queue.protocol import JobRecord

import simulate

logger = logging.getLogger(__name__)

# Shared default source of randomness for the simulated outcome. Tests inject their own stub
# to force a job to pass or fail; production uses this process-wide instance.
_DEFAULT_RNG = random.Random()

# Renew a running job's lease at half the visibility timeout, so a long-but-alive job keeps its
# claim with a safety margin before the reaper would treat it as a dead worker and requeue it.
_DEFAULT_LEASE_RENEWAL_SECONDS = settings.visibility_timeout_seconds / 2


def derive_worker_id() -> str:
    """Return this worker's id — the hostname.

    Inside a container the hostname is the short container id, so the worker reads legibly in
    the dashboard / ``ql:workers`` registry (Epic 8c).
    """
    return socket.gethostname()


async def _renew_lease_until_cancelled(
    queue: JobQueue, job_id: str, worker_id: str, interval_seconds: float
) -> None:
    """Re-stamp ``job_id``'s lease every ``interval_seconds`` until the task is cancelled.

    Renewal is best-effort: a failed renew (e.g. a transient Redis blip) is logged and the
    loop carries on, so it never aborts the job whose real outcome should drive ack/nack. If
    renewals keep failing the lease eventually lapses and the reaper (Epic 9) requeues the job
    — the already-accepted at-least-once path.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await queue.renew_lease(job_id, worker_id)
        except Exception:
            logger.exception("worker %s could not renew lease for job %s", worker_id, job_id)


async def run_one_job(
    queue: JobQueue,
    worker_id: str,
    job: JobRecord,
    *,
    rng: random.Random = _DEFAULT_RNG,
    lease_renewal_seconds: float = _DEFAULT_LEASE_RENEWAL_SECONDS,
) -> None:
    """Run a single claimed job: sleep its simulated duration, then ack or nack the outcome.

    While the job runs, a background task renews its lease every ``lease_renewal_seconds`` so a
    long-but-alive worker keeps its claim instead of having the reaper requeue it mid-flight.
    The renewer is cancelled as soon as the work finishes (short jobs never trigger one).
    """
    job_type = job.payload["type"]
    complexity = job.payload["complexity"]
    duration_ms = simulate.simulated_duration_ms(job_type, complexity, rng=rng)
    heartbeat = asyncio.create_task(
        _renew_lease_until_cancelled(queue, job.id, worker_id, lease_renewal_seconds)
    )
    try:
        await asyncio.sleep(duration_ms / 1000)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
    if simulate.simulated_job_succeeds(job_type, complexity, rng=rng):
        await queue.ack(job.id, worker_id)
    else:
        await queue.nack(job.id, worker_id, error="simulated failure")


async def run_worker(
    queue: JobQueue,
    worker_id: str,
    *,
    poll_timeout: float = 5.0,
    max_idle_polls: int | None = None,
    rng: random.Random = _DEFAULT_RNG,
    lease_renewal_seconds: float = _DEFAULT_LEASE_RENEWAL_SECONDS,
) -> None:
    """Claim and run jobs one at a time until idle.

    Each cycle blocks up to ``poll_timeout`` seconds for a job; a finite wait keeps the loop
    responsive rather than blocking forever. ``max_idle_polls=None`` loops forever — the
    production default — while a finite value stops after that many consecutive empty polls,
    so the integration test can exit once a batch has drained. ``lease_renewal_seconds`` is
    forwarded to each job so a long-running job keeps its lease alive.
    """
    idle_polls = 0
    while max_idle_polls is None or idle_polls < max_idle_polls:
        job = await queue.claim(worker_id, timeout=poll_timeout)
        if job is None:
            idle_polls += 1
            continue
        idle_polls = 0
        try:
            await run_one_job(
                queue, worker_id, job, rng=rng, lease_renewal_seconds=lease_renewal_seconds
            )
        except Exception as error:
            # One malformed job (bad payload, unknown type) must never crash the worker. Nack
            # it so the queue settles it the normal way — retry with backoff, or terminal
            # ``failed`` once retries are exhausted — and keep claiming the next job.
            logger.exception("worker %s could not run job %s", worker_id, job.id)
            await queue.nack(job.id, worker_id, error=str(error))


async def main() -> None:
    """Run the worker against the configured Redis until the process is stopped."""
    queue = JobQueue.from_settings()
    worker_id = derive_worker_id()
    try:
        await run_worker(queue, worker_id)
    finally:
        await queue.aclose()


if __name__ == "__main__":
    asyncio.run(main())
