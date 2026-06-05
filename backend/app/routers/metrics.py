"""The metrics endpoint: a snapshot of the queue's aggregate vitals (Epic 10c).

``GET /api/metrics`` returns the live per-state counts plus two derived numbers — the current
ready-queue depth and the registered worker count — so a freshly loaded dashboard can show the
queue's health without waiting for the first realtime tick. The same vitals are pushed live over
``WS /ws`` by the metrics tick; both read from :func:`app.services.metrics.compute_metrics`, so
the pulled snapshot and the pushed tick can never disagree.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_queue
from app.models.schemas import MetricsResponse
from app.queue.client import JobQueue
from app.services.metrics import compute_metrics

router = APIRouter(prefix="/api", tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> MetricsResponse:
    """Return the live queue vitals: state counts plus queue depth and worker count."""
    return MetricsResponse(**await compute_metrics(queue))
