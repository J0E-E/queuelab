"""Reusable submission validation: caps, field checks, and capacity (TDD §5.8, §5.9).

The checks the producer endpoint (Epic 7) runs before it accepts a batch:

- **Cap check** — a single batch may ask for at most ``max_jobs_per_submission`` jobs (and
  at least one). This is a pure, no-input/output check on the requested count.
- **Field checks** — the chosen job type must be one of the known kinds, complexity must sit
  in the 1..5 range, and the optional retry overrides must be non-negative and in range. All
  are pure.
- **Capacity check** — the shared queue holds at most ``max_total_queued`` jobs system-wide.
  This reads the live queue depth, so it is async; it also accounts for the whole batch size.

Each raises a guardrail error (:mod:`app.services.guardrails`) that the app shapes into the
right HTTP response, so callers never build status codes or messages themselves.
"""

from __future__ import annotations

from app.config import settings
from app.queue.client import JobQueue
from app.queue.protocol import JobType, QueueFullError
from app.services.guardrails import InvalidSubmissionError

# The 1..5 difficulty range a guest can pick (TDD §5.7). Kept here next to the check that
# enforces it so the bound and its error message stay in one place.
MIN_COMPLEXITY = 1
MAX_COMPLEXITY = 5

# Bounds for the optional retry overrides. max_retries stays a small non-negative count (well
# inside the smallint column); retry_delay_ms caps the backoff at one minute (well inside the
# integer column). Validating them up front keeps an out-of-range override from reaching the
# durable columns and triggering a write error.
MIN_RETRIES = 0
MAX_RETRIES = 10
MIN_RETRY_DELAY_MS = 0
MAX_RETRY_DELAY_MS = 60_000


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


def validate_job_type(job_type: str) -> None:
    """Check the requested job type is one of the known kinds (:class:`JobType`).

    Raises :class:`InvalidSubmissionError` (shaped to ``422``) for any unknown type, with a
    system-voice message that lists the allowed values
    (e.g. ``[ERR] --type must be one of email|report|image|webhook``).
    """
    allowed = [kind.value for kind in JobType]
    if job_type not in allowed:
        raise InvalidSubmissionError(f"[ERR] --type must be one of {'|'.join(allowed)}")


def validate_complexity(complexity: int) -> None:
    """Check the requested complexity sits in the 1..5 difficulty range (TDD §5.7).

    Raises :class:`InvalidSubmissionError` (shaped to ``422``) when ``complexity`` falls
    outside the range, with a system-voice message
    (e.g. ``[ERR] --complexity must be between 1 and 5``).
    """
    if complexity < MIN_COMPLEXITY or complexity > MAX_COMPLEXITY:
        raise InvalidSubmissionError(
            f"[ERR] --complexity must be between {MIN_COMPLEXITY} and {MAX_COMPLEXITY}"
        )


def validate_retry_settings(max_retries: int | None, retry_delay_ms: int | None) -> None:
    """Check the optional retry overrides are non-negative and in range.

    Either value may be ``None`` — the service then fills the configured default, which is
    always valid — so a ``None`` is skipped. A provided value outside its range raises
    :class:`InvalidSubmissionError` (shaped to ``422``) with a system-voice message, so a bad
    override is rejected cleanly instead of reaching the durable columns and overflowing them.
    """
    if max_retries is not None and (max_retries < MIN_RETRIES or max_retries > MAX_RETRIES):
        raise InvalidSubmissionError(
            f"[ERR] --max-retries must be between {MIN_RETRIES} and {MAX_RETRIES}"
        )
    if retry_delay_ms is not None and (
        retry_delay_ms < MIN_RETRY_DELAY_MS or retry_delay_ms > MAX_RETRY_DELAY_MS
    ):
        raise InvalidSubmissionError(
            f"[ERR] --retry-delay-ms must be between {MIN_RETRY_DELAY_MS} and {MAX_RETRY_DELAY_MS}"
        )


async def ensure_within_capacity(queue: JobQueue, count: int = 1) -> None:
    """Check the shared queue has room for the whole batch (graceful saturation).

    Raises :class:`QueueFullError` (shaped to ``409``) when accepting ``count`` more jobs would
    push the queue past ``max_total_queued``. Checking the batch size up front means an
    over-large batch is rejected cleanly rather than partially enqueued; :meth:`JobQueue.enqueue`
    keeps its own per-job soft check as a backstop. The default ``count=1`` preserves the
    original "is the queue already full?" behaviour for existing callers.
    """
    cap = settings.max_total_queued
    if await queue.total_queued() + count > cap:
        raise QueueFullError(f"queue at capacity ({cap} queued)")
