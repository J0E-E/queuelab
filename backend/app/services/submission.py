"""The submit-a-batch flow: validate, persist, enqueue (TDD §5.12, Epic 7).

This is the producer side of the core flow. One call, :func:`submit_batch`, runs the
guardrails, writes a durable ``job`` row per requested job to Postgres, then pushes each
job's id onto the Redis ready queue for a worker to claim. The route layer (``POST
/api/jobs``) stays thin: it parses the body, calls this, and returns the result.

Ordering and trade-offs (deliberate, single-instance assumptions):

- **Durable first, then enqueue** (matches TDD §5.12): the ``job`` rows are committed before
  anything lands on the queue, so a job is never runnable without a durable record behind it.
- **Same id in both stores:** one UUID per job is used verbatim as the Postgres primary key
  and the Redis job id, so the durable-writer (Epic 10) can match a state-change event to its
  row.
- **All-or-nothing:** the batch is validated and capacity-checked up front; on success every
  job is accepted (``accepted == count``), never a partial batch. There is no cross-store
  transaction, so a mid-batch enqueue failure can leave committed rows that never run — an
  accepted edge consistent with the queue's documented best-effort enqueue (Epic 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.config import settings
from app.db.engine import Database
from app.models.job import Job
from app.models.schemas import BatchSubmitResponse, JobSubmission
from app.queue.client import JobQueue
from app.queue.protocol import JobRecord, JobState
from app.services.guardrails import InvalidSubmissionError
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore
from app.services.validation import (
    ensure_within_capacity,
    validate_complexity,
    validate_job_type,
    validate_retry_settings,
    validate_submission_count,
)


async def submit_batch(
    submission: JobSubmission,
    *,
    queue: JobQueue,
    database: Database,
    rate_limiter: RateLimiter,
    session_store: SessionStore,
) -> BatchSubmitResponse:
    """Validate a batch, write its durable rows, enqueue it, and report what was accepted.

    Runs the guardrails in order — field validation (``422``), the session lookup that yields
    the trusted handle (``422`` if unknown/expired), batch capacity (``409``), then the rate
    limit (``429``) — each raising an error already wired to its HTTP response. Capacity is
    checked before the rate limit so a full-queue rejection does not spend the session's
    rate-limit token. On success, commits one ``job`` row per requested job and enqueues each,
    returning the batch's correlation id and accepted count.
    """
    # 1. Guardrails. Cheap, pure field checks first so a malformed request is rejected without
    #    any I/O. Then resolve the trusted guest handle from the session record — the body's
    #    session_id is the only identity we believe, and the handle is derived, never accepted
    #    from the client. Capacity precedes the rate limit so a 409 leaves the token unspent.
    validate_submission_count(submission.count)
    validate_job_type(submission.type)
    validate_complexity(submission.complexity)
    validate_retry_settings(submission.max_retries, submission.retry_delay_ms)
    guest_handle = await session_store.get_handle(submission.session_id)
    if guest_handle is None:
        raise InvalidSubmissionError("[ERR] unknown or expired session — refresh the page")
    await ensure_within_capacity(queue, submission.count)
    await rate_limiter.check_submission(submission.session_id)

    # 2. Fill optional retry settings from the configured defaults when the client omits them.
    max_retries = submission.max_retries
    if max_retries is None:
        max_retries = settings.default_max_retries
    retry_delay_ms = submission.retry_delay_ms
    if retry_delay_ms is None:
        retry_delay_ms = settings.default_retry_delay_ms
    submitted_at = datetime.now(UTC)

    # 3. Build a correlated (durable row, hot record) pair per job, sharing one id.
    rows: list[Job] = []
    records: list[JobRecord] = []
    for _ in range(submission.count):
        job_id = uuid4()
        rows.append(
            Job(
                id=job_id,
                session_id=submission.session_id,
                guest_handle=guest_handle,
                type=submission.type,
                complexity=submission.complexity,
                max_retries=max_retries,
                retry_delay_ms=retry_delay_ms,
                state=JobState.QUEUED.value,
                attempts=0,
                submitted_at=submitted_at,
            )
        )
        records.append(
            JobRecord(
                id=str(job_id),
                session_id=submission.session_id,
                payload={"type": submission.type, "complexity": submission.complexity},
                max_retries=max_retries,
                retry_delay_ms=retry_delay_ms,
            )
        )

    # 4. Persist the durable records in one transaction, then make them runnable.
    async with database.session() as session:
        session.add_all(rows)
        await session.commit()
    for record in records:
        await queue.enqueue(record)

    return BatchSubmitResponse(batch_id=uuid4().hex, accepted=submission.count)
