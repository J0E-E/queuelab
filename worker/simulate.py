"""Simulated work profiles for the QueueLab worker (TDD §5.4).

Pure, dependency-free functions the worker's claim loop (Epic 8b) calls to decide how long
a job "takes" and whether it succeeds or fails. There are no real side effects — only the
work each job performs is simulated; the queue mechanics around it are genuine.

Per TDD §5.4 the profiles are keyed by job *type* and scaled by *complexity* (1..5)::

    duration_ms      = round(base_duration_ms[type] * complexity * jitter)
    fail_probability = clamp(base_failure_rate[type] * complexity + failure_bias, 0, 1)

The profile dicts are keyed by the four literal type strings ("email", "report", "image",
"webhook"). These mirror :class:`app.queue.protocol.JobType` deliberately: that enum is the
one canonical vocabulary, but this module stays dependency-free (it does not import the
backend ``app`` package). Because ``JobType`` is a ``StrEnum``, a member like
``JobType.EMAIL`` *is* the string ``"email"``, so once the worker vendors ``app.queue``
(Epic 8b) it can pass ``JobType`` members straight into these functions with no friction.

Inputs are trusted: the submission endpoint (Epic 7) already validates that ``type`` is a
known ``JobType`` and ``complexity`` is 1..5, so these functions do not re-validate the
range. An unknown type raises a clear :class:`ValueError`.
"""

from __future__ import annotations

import random

# Per-type base profiles ("Snappy" feel — every duration stays well under the 30s lease).
# Keys mirror app.queue.protocol.JobType (see module docstring). TDD §7 marks these exact
# numbers as open/tunable; tune them here.
BASE_DURATION_MS: dict[str, int] = {
    "email": 300,
    "webhook": 500,
    "report": 800,
    "image": 1000,
}

BASE_FAILURE_RATE: dict[str, float] = {
    "email": 0.02,
    "webhook": 0.03,
    "report": 0.04,
    "image": 0.05,
}

# Multiplicative jitter applied to each duration so identical jobs don't all take exactly
# the same time (keeps the worker grid lively) — ±15% around the complexity-scaled base.
JITTER_RANGE: tuple[float, float] = (0.85, 1.15)

# Shared default source of randomness. Tests inject their own seeded ``random.Random`` (or a
# small stub) to pin exact values; production uses this process-wide instance.
_DEFAULT_RNG = random.Random()


def _require_known_type(job_type: str) -> None:
    """Raise :class:`ValueError` if ``job_type`` has no profile (both dicts share keys)."""
    if job_type not in BASE_DURATION_MS:
        raise ValueError(f"unknown job type: {job_type!r}")


def simulated_duration_ms(
    job_type: str,
    complexity: int,
    *,
    rng: random.Random = _DEFAULT_RNG,
) -> int:
    """Return how long this job should "take", in whole milliseconds (TDD §5.4).

    Scales the per-type base linearly by ``complexity`` (1..5) and applies ±15% jitter.
    Returns an integer to match the durable ``job.duration_ms`` column; the worker
    (Epic 8b) divides by 1000 to sleep. Raises :class:`ValueError` for an unknown type.
    """
    _require_known_type(job_type)
    jitter = rng.uniform(*JITTER_RANGE)
    return round(BASE_DURATION_MS[job_type] * complexity * jitter)


def simulated_job_succeeds(
    job_type: str,
    complexity: int,
    *,
    rng: random.Random = _DEFAULT_RNG,
    failure_bias: float = 0.0,
) -> bool:
    """Return ``True`` if the job succeeds, ``False`` if it fails (TDD §5.4).

    Failure probability is the per-type base scaled by ``complexity`` plus an optional
    ``failure_bias`` — the global inject-failures chaos term (Epic 12) — clamped to
    ``[0, 1]``. With the default ``failure_bias=0.0`` the bias term has no effect. Raises
    :class:`ValueError` for an unknown type.
    """
    _require_known_type(job_type)
    fail_probability = min(1.0, max(0.0, BASE_FAILURE_RATE[job_type] * complexity + failure_bias))
    return rng.random() >= fail_probability
