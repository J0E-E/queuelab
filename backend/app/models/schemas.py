"""Pydantic request and response shapes (DTOs) for the job endpoints.

The response views (``JobResponse``, ``ScalingEventResponse``, ``JobPage``) are read-side
shapes returned by the REST endpoints. ``from_attributes=True`` lets each one be built
straight from an ORM row (``JobResponse.model_validate(job_row)``), so the route layer never
hand-copies fields. ``JobSubmission`` is the write-side body for ``POST /api/jobs``; bad
*values* (count/complexity out of range, an unknown type, an out-of-range retry override)
are checked in :mod:`app.services.validation` so those rejections come back in the system
voice the UI renders. A wrong *type* (e.g. a non-integer ``count``) still falls back to
Pydantic's default error shape.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobSubmission(BaseModel):
    """The body for ``POST /api/jobs`` — one batch request (TDD §5.8).

    Only ``session_id`` identifies the caller: the trusted ``guest_handle`` is derived
    server-side from the session record (see :mod:`app.services.session_store`), so a client
    cannot submit under a handle it does not own. ``max_retries`` and ``retry_delay_ms`` are
    optional; when omitted the service fills them from the configured defaults. Out-of-range
    *values* are caught by the validation service so the rejection comes back in the system
    voice ``[ERR] ...``.
    """

    session_id: str
    count: int
    type: str
    complexity: int
    max_retries: int | None = None
    retry_delay_ms: int | None = None


class BatchSubmitResponse(BaseModel):
    """The ``201`` body for a successful submission: a correlation id and accepted count.

    ``batch_id`` is a throwaway id the client can use to refer to this submission (e.g. in the
    activity feed). It is not stored — the durable records are the individual ``job`` rows,
    each with its own id. ``accepted`` equals the requested ``count`` because a batch is
    all-or-nothing (no partial accept).
    """

    batch_id: str
    accepted: int


class JobResponse(BaseModel):
    """A durable job row as the API returns it.

    Exposes ``worker_id`` on purpose (Epic 7 decision): it reinforces the verifiable-record
    story — a guest can see which worker ran their job. ``session_id`` is deliberately *not*
    returned: ``GET /api/jobs`` is unscoped, and ``session_id`` is the rate-limit / identity
    key, so leaking it would let one visitor grief another's submit budget or spoof their
    attribution. The frontend keys off ``guest_handle`` instead.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    guest_handle: str
    type: str
    complexity: int
    max_retries: int
    retry_delay_ms: int
    state: str
    attempts: int
    worker_id: str | None
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    last_error: str | None


class JobPage(BaseModel):
    """One page of job records plus the totals the UI needs to show paging (Epic 7).

    ``items`` is the current page (newest first); ``total`` is how many rows match the filters
    across every page, so the UI can render "showing 50 of 137". ``limit``/``offset`` echo the
    paging window that produced this page.
    """

    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class ScalingEventResponse(BaseModel):
    """A scaling-event row as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    action: str
    worker_id: str | None
    reason: str | None
    worker_count_after: int
