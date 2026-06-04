"""QueueLab worker — the consumer side of the core flow (Epics 8b, 8c).

A real worker process: it claims a job from the custom Redis queue, runs it through the
simulated work profile (Epic 8a's :mod:`simulate`), and acknowledges success (``ack``) or
failure (``nack``). Each cycle handles one job — claim, run, settle — so a submitted batch
genuinely drains.

The queue mechanics are real: ``claim`` is an all-at-once or not-at-all (atomic) blocking
grab-and-move, leases are real, and a failed job either retries with backoff or goes
terminally ``failed``. Only the work each job performs is simulated.

Epic 8c makes the worker a well-behaved citizen. It **registers and heartbeats** in
``ql:workers`` so the autoscaler (Epic 11) can see it is alive and what it is doing, and on a
**graceful SIGTERM** (Docker stop) it stops claiming, cleanly returns its in-flight job to the
ready queue without burning a retry, then exits. A hard SIGKILL is intentionally left to the
lease-expiry reaper (Epic 9) — the more impressive chaos demo.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import signal
import socket
from dataclasses import dataclass

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

# How often the worker refreshes its liveness in ``ql:workers`` (config-driven).
_DEFAULT_HEARTBEAT_SECONDS = settings.worker_heartbeat_seconds


@dataclass
class _WorkerStatus:
    """The worker's live status, shared with the heartbeat task and refreshed in the loop.

    ``state`` is a worker-liveness vocabulary distinct from the job states: ``idle`` while
    polling, ``busy`` while running a job, ``stopping`` during a graceful drain.
    """

    state: str = "idle"
    current_job: str | None = None


def derive_worker_id() -> str:
    """Return this worker's id — the hostname.

    Inside a container the hostname is the short container id, so the worker reads legibly in
    the dashboard / ``ql:workers`` registry.
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


async def _heartbeat_until_cancelled(
    queue: JobQueue, worker_id: str, status: _WorkerStatus, interval_seconds: float
) -> None:
    """Refresh the worker's ``ql:workers`` record every ``interval_seconds`` until cancelled.

    Like lease renewal this is best-effort: a failed heartbeat is logged and the loop carries
    on, so a transient Redis blip never takes the worker down. If heartbeats keep failing the
    record goes stale and the autoscaler (Epic 11) reaps the worker — the same liveness path a
    dead worker takes.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await queue.heartbeat(worker_id, state=status.state, current_job=status.current_job)
        except Exception:
            logger.exception("worker %s could not refresh its heartbeat", worker_id)


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


async def _run_job_until_done_or_stopped(
    queue: JobQueue,
    worker_id: str,
    job: JobRecord,
    stop_event: asyncio.Event,
    *,
    rng: random.Random,
    lease_renewal_seconds: float,
) -> bool:
    """Run a claimed job, but abort and cleanly requeue it if ``stop_event`` fires first.

    Returns ``True`` if shutdown was requested mid-flight and the job was handed back to the
    ready queue (so the loop should stop), or ``False`` if the job ran to its normal ack/nack
    settlement. A graceful requeue never burns a retry — it is not a failed attempt.
    """
    job_task = asyncio.create_task(
        run_one_job(queue, worker_id, job, rng=rng, lease_renewal_seconds=lease_renewal_seconds)
    )
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {job_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if job_task in done:
            # Normal settlement (ack/nack already happened inside run_one_job). Re-raise a
            # malformed-job error so the caller's nack path handles it.
            job_task.result()
            return False
        # Shutdown requested mid-job: cancel the simulated work and hand the job straight back.
        job_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await job_task
        await queue.requeue(job.id, worker_id)
        return True
    finally:
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task


async def run_worker(
    queue: JobQueue,
    worker_id: str,
    *,
    poll_timeout: float = 5.0,
    max_idle_polls: int | None = None,
    rng: random.Random = _DEFAULT_RNG,
    lease_renewal_seconds: float = _DEFAULT_LEASE_RENEWAL_SECONDS,
    stop_event: asyncio.Event | None = None,
    heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
) -> None:
    """Claim and run jobs one at a time until idle or asked to stop.

    Each cycle blocks up to ``poll_timeout`` seconds for a job; a finite wait keeps the loop
    responsive rather than blocking forever. ``max_idle_polls=None`` loops forever — the
    production default — while a finite value stops after that many consecutive empty polls,
    so the integration test can exit once a batch has drained.

    The worker registers in ``ql:workers`` up front and refreshes its heartbeat every
    ``heartbeat_seconds`` for its whole life, deregistering cleanly on exit. When ``stop_event``
    is set (a graceful SIGTERM), the loop stops claiming and cleanly requeues any in-flight job
    without burning a retry; left unset it never fires, so the loop behaves as before.
    """
    if stop_event is None:
        stop_event = asyncio.Event()
    status = _WorkerStatus()

    # Register immediately (the first heartbeat) so the worker is visible before its first claim.
    await queue.heartbeat(worker_id, state=status.state, current_job=status.current_job)
    heartbeat_task = asyncio.create_task(
        _heartbeat_until_cancelled(queue, worker_id, status, heartbeat_seconds)
    )
    try:
        idle_polls = 0
        while not stop_event.is_set() and (max_idle_polls is None or idle_polls < max_idle_polls):
            job = await queue.claim(worker_id, timeout=poll_timeout)
            if job is None:
                idle_polls += 1
                continue
            idle_polls = 0
            status.state = "busy"
            status.current_job = job.id
            try:
                was_requeued = await _run_job_until_done_or_stopped(
                    queue,
                    worker_id,
                    job,
                    stop_event,
                    rng=rng,
                    lease_renewal_seconds=lease_renewal_seconds,
                )
            except Exception as error:
                # One malformed job (bad payload, unknown type) must never crash the worker.
                # Nack it so the queue settles it the normal way — retry with backoff, or
                # terminal ``failed`` once retries are exhausted — and keep claiming.
                logger.exception("worker %s could not run job %s", worker_id, job.id)
                await queue.nack(job.id, worker_id, error=str(error))
                was_requeued = False
            finally:
                status.state = "idle"
                status.current_job = None
            if was_requeued:
                break
    finally:
        # Stop the periodic heartbeat, then publish one final `stopping` record (best-effort) so
        # the autoscaler can briefly see the graceful drain, before deregistering on the way out.
        status.state = "stopping"
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        try:
            await queue.heartbeat(worker_id, state=status.state, current_job=status.current_job)
        except Exception:
            logger.exception("worker %s could not publish its stopping heartbeat", worker_id)
        await queue.deregister_worker(worker_id)


async def main() -> None:
    """Run the worker against the configured Redis until the process is stopped."""
    queue = JobQueue.from_settings()
    worker_id = derive_worker_id()
    stop_event = asyncio.Event()

    # Docker stop sends SIGTERM; Ctrl-C in local dev sends SIGINT. Both trigger a graceful
    # drain. add_signal_handler isn't implemented on Windows (dev-only — the worker runs in a
    # Linux container), so suppress that and fall back to no handler there.
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signal_number, stop_event.set)

    try:
        await run_worker(queue, worker_id, stop_event=stop_event)
    finally:
        await queue.aclose()


if __name__ == "__main__":
    asyncio.run(main())
