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


class QueueCounts(BaseModel):
    """The live per-state job tallies from the queue's counts hash (Epic 10c).

    ``queued``/``running``/``retrying`` are point-in-time (jobs currently in that state);
    ``completed``/``failed`` are cumulative lifetime totals that only ever climb. ``recovered`` is
    a cumulative subset of ``completed`` — jobs that finished only after at least one failed attempt
    (a retry or reaper recovery that succeeded). The fields mirror ``COUNT_FIELDS`` exactly.
    """

    queued: int
    running: int
    completed: int
    failed: int
    retrying: int
    recovered: int


class WorkerHealth(BaseModel):
    """One worker's liveness for the grid: stable id, heartbeat freshness, and whether it's busy.

    ``healthy`` is ``False`` once the heartbeat is stale, so the grid can paint a destroyed/crashed
    worker as dying; ``busy`` distinguishes a worker running a job from an idle one.
    """

    id: str
    healthy: bool
    busy: bool


class MetricsResponse(BaseModel):
    """The queue's aggregate vitals returned by ``GET /api/metrics`` (Epic 10c).

    ``counts`` is the live per-state tally; ``queue_depth`` is how many jobs are waiting on the
    ready queue right now (read straight from the list, the authoritative depth); ``worker_count``
    is how many workers are registered in ``ql:workers``; ``unhealthy_worker_count`` is how many of
    those have a stale heartbeat; ``workers`` is the per-worker detail (id + liveness) the grid
    renders each cell from. The metrics tick pushes this same shape over ``WS /ws`` as a
    ``{"type": "metrics", ...}`` frame, so the pulled snapshot and the live tick agree.
    """

    counts: QueueCounts
    queue_depth: int
    worker_count: int
    unhealthy_worker_count: int
    workers: list[WorkerHealth]


class InjectFailuresRequest(BaseModel):
    """The body for ``POST /api/chaos/inject-failures`` (Epic 12).

    ``session_id`` keys the per-session chaos rate limit (the same throttle as a submission).
    ``bias`` is added to every simulated job's failure probability while the injection lives; a
    value outside ``0..1`` is rejected by the chaos service in the system voice.
    """

    session_id: str
    bias: float


class InjectFailuresResponse(BaseModel):
    """The body returned after a failure injection: the bias set and how long it lasts."""

    bias: float
    ttl_seconds: int


class DestroyWorkerRequest(BaseModel):
    """The body for ``POST /api/chaos/destroy-worker`` (Epic 12).

    ``session_id`` keys the per-session chaos rate limit. ``worker_id`` is optional: the frontend
    grid passes the worker the operator clicked, while the generic "break something" button omits
    it and lets the api pick a live worker at random.
    """

    session_id: str
    worker_id: str | None = None


class DestroyWorkerResponse(BaseModel):
    """The body returned after a destroy is dispatched: which worker was targeted."""

    worker_id: str


class ArchitectureSection(BaseModel):
    """One in-context architecture note (Epic 15): a pane key, a title, and explanatory copy."""

    key: str
    title: str
    body: str


class ArchitectureResponse(BaseModel):
    """The body of ``GET /api/architecture`` — the ordered architecture notes for the UI."""

    sections: list[ArchitectureSection]


class AutoscalerConfig(BaseModel):
    """The autoscaler thresholds in force, returned by ``GET /api/config`` (Epic 11d-2).

    These are the *effective* values: the env-loaded defaults with any live ``ql:config`` override
    applied on top, i.e. exactly what the control loop reasons over right now. The keys mirror
    :data:`app.config.OVERRIDABLE_CONFIG_KEYS`.
    """

    min_workers: int
    max_workers: int
    scale_up_threshold: int
    scale_down_threshold: int
    idle_timeout_seconds: int


class AutoscalerConfigUpdate(BaseModel):
    """The body for ``PUT /api/config`` — a partial patch of autoscaler thresholds (Epic 11d-2).

    Every field is optional: only the keys present are written, leaving the others at their prior
    override or env default. An unknown key is rejected (``extra="forbid"``) so a typo surfaces
    rather than being silently dropped. The *values* are validated by re-building the full
    :class:`app.config.Settings` from the merged result, so a cross-field violation (e.g.
    ``scale_down_threshold`` above ``scale_up_threshold``) comes back as a system-voice ``[ERR]``.
    """

    model_config = ConfigDict(extra="forbid")

    min_workers: int | None = None
    max_workers: int | None = None
    scale_up_threshold: int | None = None
    scale_down_threshold: int | None = None
    idle_timeout_seconds: int | None = None


class ScalingEventResponse(BaseModel):
    """A scaling-event row as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    action: str
    worker_id: str | None
    reason: str | None
    worker_count_after: int
