"""Chaos actions — the "break it on purpose" mechanics (Epic 12).

Two operator levers, both rate-limited through the shared chaos bucket:

- :func:`inject_failures` writes a live failure-bias to Redis with a TTL, so simulated jobs start
  failing more often for a while and then recover on their own.
- :func:`destroy_worker` (Phase 2) publishes a ``destroy`` command on ``ql:control`` so the
  autoscaler hard-kills a worker and the queue's recovery path (reaper + replace) kicks in.

The route layer stays thin: it parses the body and calls one of these. Validation failures raise
the shared guardrail errors (:mod:`app.services.guardrails`) so the rejection comes back in the
system voice the UI renders.
"""

from __future__ import annotations

import random

from app.config import settings
from app.queue.client import JobQueue
from app.services.guardrails import InvalidSubmissionError, NoWorkersError
from app.services.rate_limit import RateLimiter


async def inject_failures(
    bias: float,
    *,
    queue: JobQueue,
    rate_limiter: RateLimiter,
    session_id: str,
) -> float:
    """Bias simulated outcomes toward failure for a while, then let it self-expire.

    Validates the bias first (a bad value is rejected before the rate-limit token is spent),
    rate-limits the chaos action, then stores the bias with the configured TTL so workers pick it
    up on their next job and it decays back to normal on its own. Returns the bias that was set.
    """
    _validate_bias(bias)
    await rate_limiter.check_chaos(session_id)
    await queue.set_failure_bias(bias, ttl_seconds=settings.chaos_failure_ttl_seconds)
    return bias


def _validate_bias(bias: float) -> None:
    """Reject a failure-bias outside ``0..1`` with a system-voice ``422`` message."""
    if not 0.0 <= bias <= 1.0:
        raise InvalidSubmissionError("[ERR] bias must be between 0 and 1")


async def destroy_worker(
    *,
    queue: JobQueue,
    rate_limiter: RateLimiter,
    session_id: str,
    worker_id: str | None = None,
) -> str:
    """Hard-kill a worker via the autoscaler so its in-flight job recovers, and report the target.

    Resolves the target against the live registry first — the caller's ``worker_id`` (the frontend
    grid click) *must* name a registered worker, else a random live worker is picked (the generic
    "break something" button) — and rejects with a ``409`` if there is no such worker, before the
    rate-limit token is spent. Validating the supplied id against ``ql:workers`` is a security
    boundary: ``kill_worker`` removes a container by name with no label filter, so without this an
    unauthenticated caller could name ``postgres`` / ``redis`` / ``api`` and destroy core
    infrastructure. Then it rate-limits the chaos action and publishes a ``destroy`` command on
    ``ql:control``; the autoscaler (the only process holding the Docker socket) carries it out,
    leaving the registry entry stale so the reaper recovers the worker's in-flight job.
    """
    workers = await queue.list_workers()
    if worker_id is not None:
        if worker_id not in workers:
            raise NoWorkersError(f"[WARN] no such worker to destroy: {worker_id}")
        target: str | None = worker_id
    else:
        target = _pick_random_worker(workers)
    if not target:
        raise NoWorkersError("[WARN] no workers to destroy")
    await rate_limiter.check_chaos(session_id)
    await queue.publish_control_command({"command": "destroy", "worker_id": target})
    return target


def _pick_random_worker(workers: dict[str, dict]) -> str | None:
    """Return a random worker id from the live registry, or ``None`` when the fleet is empty."""
    if not workers:
        return None
    return random.choice(list(workers))
