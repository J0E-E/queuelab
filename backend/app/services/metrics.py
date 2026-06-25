"""Compute the queue's aggregate vitals for the dashboard (Epic 10c).

The dashboard wants a single read of the queue's health: the live per-state counts plus two
derived numbers — how deep the ready queue is right now and how many workers are registered.
This one helper is the single source for both ways those vitals reach the browser: the
``GET /api/metrics`` snapshot a freshly loaded page reads once, and the throttled metrics tick
the realtime layer pushes over ``WS /ws``. One function behind both means the pulled snapshot
and the pushed tick can never disagree.

It is a thin read over the existing queue helpers (:meth:`JobQueue.counts`,
:meth:`JobQueue.queue_depth`, :meth:`JobQueue.list_workers`) — no new Redis access — and returns
a plain dict so the realtime frame can spread it straight into its envelope while the REST layer
validates it into :class:`app.models.schemas.MetricsResponse`.

The worker count is every registered worker in ``ql:workers``; pruning a hard-killed worker by
stale heartbeat age is the autoscaler's job (Epic 11). Alongside it we report how many of those
workers are *unhealthy* — heartbeat already stale — so the grid can paint a destroyed/crashed
worker as dying (a ✗ cell) in the seconds before the autoscaler replaces it, instead of leaving it
looking like a healthy idle worker.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.queue.client import JobQueue


async def compute_metrics(queue: JobQueue) -> dict[str, Any]:
    """Return the live queue vitals: counts, queue depth, worker count, and per-worker liveness.

    The shape — ``{"counts": {...}, "queue_depth": int, "worker_count": int,
    "unhealthy_worker_count": int, "workers": [{"id", "healthy", "busy"}]}`` — mirrors the snapshot
    frame's ``counts`` block, so the metrics tick wraps it as ``{"type": "metrics", ...}`` like the
    snapshot wraps its counts. ``workers`` is the per-worker detail the grid renders each cell from;
    the two counts are convenience aggregates over it.
    """
    counts = await queue.counts()
    queue_depth = await queue.queue_depth()
    registry = await queue.list_workers()
    now_ms = await queue.now_ms()
    workers = _worker_health(registry, now_ms=now_ms)
    return {
        "counts": counts,
        "queue_depth": queue_depth,
        "worker_count": len(workers),
        "unhealthy_worker_count": sum(1 for worker in workers if not worker["healthy"]),
        "workers": workers,
    }


def _worker_health(registry: dict[str, dict], *, now_ms: int) -> list[dict[str, Any]]:
    """Per-worker liveness for the grid: each worker's id, heartbeat freshness, and busy flag.

    A worker is ``healthy`` while its last heartbeat is within two refresh intervals; past that it
    is treated as dying, so a destroyed or crashed worker is flagged a few seconds *before* the
    autoscaler's ``worker_unhealthy_after_seconds`` replace fires — a visible "it's gone" cue.
    A healthy worker beats every interval, so its heartbeat never drifts past this. Sorted by id so
    the grid's cell order is stable from tick to tick.
    """
    stale_after_ms = settings.worker_heartbeat_seconds * 2 * 1000
    return [
        {
            "id": worker_id,
            "healthy": now_ms - record["last_heartbeat"] <= stale_after_ms,
            "busy": record.get("state") == "busy",
        }
        for worker_id, record in sorted(registry.items())
    ]
