"""Reusable submission validation: caps and capacity (TDD §5.8, §5.9).

Two checks the producer endpoint (Epic 7) runs before it accepts a batch:

- **Cap check** — a single batch may ask for at most ``max_jobs_per_submission`` jobs (and
  at least one). This is a pure, no-input/output check on the requested count.
- **Capacity check** — the shared queue holds at most ``max_total_queued`` jobs system-wide.
  This reads the live queue depth, so it is async.

Both raise a guardrail error (:mod:`app.services.guardrails`) that the app shapes into the
right HTTP response, so callers never build status codes or messages themselves.
"""

from __future__ import annotations

from app.config import settings
from app.queue.client import JobQueue
from app.queue.protocol import QueueFullError
from app.services.guardrails import InvalidSubmissionError


def validate_submission_count(count: int) -> None:
    """Check a batch's requested job count against the per-submission cap.

    Raises :class:`InvalidSubmissionError` (shaped to ``422``) when ``count`` is below 1 or
    above ``max_jobs_per_submission``, with the system-voice message the UI renders beneath
    the offending flag (e.g. ``[ERR] --count exceeds cap (max 100)``).
    """
    cap = settings.max_jobs_per_submission
    if count < 1:
        raise InvalidSubmissionError("[ERR] --count must be at least 1")
    if count > cap:
        raise InvalidSubmissionError(f"[ERR] --count exceeds cap (max {cap})")


async def ensure_within_capacity(queue: JobQueue) -> None:
    """Check the shared queue has room before accepting more work (graceful saturation).

    Raises :class:`QueueFullError` (shaped to ``409``) when the queue already holds
    ``max_total_queued`` jobs. This is a pre-check so the endpoint can reject cleanly up
    front; :meth:`JobQueue.enqueue` keeps its own soft check as a backstop.
    """
    if await queue.total_queued() >= settings.max_total_queued:
        raise QueueFullError(f"queue at capacity ({settings.max_total_queued} queued)")
