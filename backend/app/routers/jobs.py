"""The job endpoints: submit a batch and read durable job records (TDD §5.8, Epic 7).

``POST /api/jobs`` is the producer side of the core flow — it validates a batch, writes the
durable rows, and enqueues the work (see :mod:`app.services.submission`). ``GET /api/jobs``
is the read-back: a paged, filterable view of the durable ``job`` rows so a guest can verify
their submission landed and watch each job's outcome.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.db.engine import Database
from app.dependencies import get_database, get_queue, get_rate_limiter, get_session_store
from app.models.job import Job
from app.models.schemas import BatchSubmitResponse, JobPage, JobResponse, JobSubmission
from app.queue.client import JobQueue
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore
from app.services.submission import submit_batch

router = APIRouter(prefix="/api", tags=["jobs"])

# Paging bounds for GET /api/jobs: a sensible default page and a hard ceiling so one request
# can't pull an unbounded slice of the table, plus a ceiling on how deep paging can reach so a
# caller can't ask for an arbitrarily large (expensive) offset. With 24h retention the table
# stays small, so this depth is far beyond any real page.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200
MAX_PAGE_OFFSET = 10_000


@router.post("/jobs", response_model=BatchSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_jobs(
    submission: JobSubmission,
    queue: Annotated[JobQueue, Depends(get_queue)],
    database: Annotated[Database, Depends(get_database)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> BatchSubmitResponse:
    """Accept a validated batch and return ``201 {batch_id, accepted}``.

    All the work — guardrails, durable writes, and enqueue — lives in
    :func:`app.services.submission.submit_batch`; over-limit batches raise guardrail errors
    that the registered handlers shape into ``422``/``429``/``409`` responses.
    """
    return await submit_batch(
        submission,
        queue=queue,
        database=database,
        rate_limiter=rate_limiter,
        session_store=session_store,
    )


@router.get("/jobs", response_model=JobPage)
async def list_jobs(
    database: Annotated[Database, Depends(get_database)],
    session: str | None = None,
    state: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> JobPage:
    """Return one page of durable job records, newest first, with the matching total.

    ``session`` and ``state`` are optional filters; an unknown ``state`` simply yields an empty
    page rather than an error (lenient). ``limit`` is clamped to 1..200 and ``offset`` to
    0..10000 so a caller can't request an unbounded, negative, or arbitrarily deep window.
    """
    page_limit = max(1, min(limit, MAX_PAGE_LIMIT))
    page_offset = max(0, min(offset, MAX_PAGE_OFFSET))

    filters = []
    if session is not None:
        filters.append(Job.session_id == session)
    if state is not None:
        filters.append(Job.state == state)

    async with database.session() as db_session:
        total = await db_session.scalar(select(func.count()).select_from(Job).where(*filters))
        # Order by submission time, then id, so jobs in one batch (which share a timestamp)
        # keep a stable order across pages.
        rows = await db_session.scalars(
            select(Job)
            .where(*filters)
            .order_by(Job.submitted_at.desc(), Job.id)
            .limit(page_limit)
            .offset(page_offset)
        )
        items = [JobResponse.model_validate(row) for row in rows]

    return JobPage(items=items, total=total or 0, limit=page_limit, offset=page_offset)
