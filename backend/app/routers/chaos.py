"""The chaos endpoints: break things on purpose to show the queue recovering (Epic 12).

``POST /api/chaos/inject-failures`` biases simulated outcomes toward failure for a while, and
``POST /api/chaos/destroy-worker`` hard-kills a worker so its in-flight job is recovered by the
reaper and the autoscaler stands up a replacement. Both are rate-limited through the shared chaos
bucket and surface in the activity feed. The routes stay thin — they parse the body and hand off to
:mod:`app.services.chaos`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import get_queue, get_rate_limiter, get_session_store
from app.models.schemas import (
    DestroyWorkerRequest,
    DestroyWorkerResponse,
    InjectFailuresRequest,
    InjectFailuresResponse,
)
from app.queue.client import JobQueue
from app.services.chaos import destroy_worker, inject_failures
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore

router = APIRouter(prefix="/api/chaos", tags=["chaos"])


@router.post("/inject-failures", response_model=InjectFailuresResponse)
async def inject_failures_endpoint(
    request: InjectFailuresRequest,
    queue: Annotated[JobQueue, Depends(get_queue)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> InjectFailuresResponse:
    """Inject a failure-bias that workers pick up on their next job and that self-expires."""
    bias = await inject_failures(
        request.bias, queue=queue, rate_limiter=rate_limiter, session_id=request.session_id
    )
    return InjectFailuresResponse(bias=bias, ttl_seconds=settings.chaos_failure_ttl_seconds)


@router.post("/destroy-worker", response_model=DestroyWorkerResponse)
async def destroy_worker_endpoint(
    request: DestroyWorkerRequest,
    queue: Annotated[JobQueue, Depends(get_queue)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> DestroyWorkerResponse:
    """Hard-kill a worker (the given one, or a random live one) and let the queue recover it."""
    target = await destroy_worker(
        queue=queue,
        rate_limiter=rate_limiter,
        session_store=session_store,
        session_id=request.session_id,
        worker_id=request.worker_id,
    )
    return DestroyWorkerResponse(worker_id=target)
