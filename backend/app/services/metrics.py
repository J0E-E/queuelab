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
stale heartbeat age is the autoscaler's job (Epic 11), so this stays a plain count.
"""

from __future__ import annotations

from typing import Any

from app.queue.client import JobQueue


async def compute_metrics(queue: JobQueue) -> dict[str, Any]:
    """Return the live queue vitals: the state counts plus queue depth and worker count.

    The shape — ``{"counts": {...}, "queue_depth": int, "worker_count": int}`` — mirrors the
    snapshot frame's ``counts`` block, so the metrics tick can wrap it as
    ``{"type": "metrics", ...}`` exactly the way the snapshot wraps its own counts.
    """
    counts = await queue.counts()
    queue_depth = await queue.queue_depth()
    workers = await queue.list_workers()
    return {
        "counts": counts,
        "queue_depth": queue_depth,
        "worker_count": len(workers),
    }
