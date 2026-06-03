"""Pydantic response shapes (DTOs) for the durable records.

These are the read-side views returned by the REST endpoints in later epics
(``GET /api/jobs``, the metrics/feed reads). ``from_attributes=True`` lets each one be
built straight from an ORM row (``JobResponse.model_validate(job_row)``), so the route
layer never hand-copies fields.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    """A durable job row as the API returns it.

    Note for the read endpoint (Epic 7, ``GET /api/jobs``): this includes the internal
    ``session_id`` and ``worker_id``. Confirm those should be visible to clients — or drop
    them from the response shape — before that endpoint ships.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: str
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


class ScalingEventResponse(BaseModel):
    """A scaling-event row as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    action: str
    worker_id: str | None
    reason: str | None
    worker_count_after: int
