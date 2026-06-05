"""The autoscaler's brain: a pure scaling-decision function (Epic 11a).

The autoscaler (Epic 11) needs to decide *what* to do before it grows hands to do it. This
module is that decision, in isolation: :func:`decide_scaling` takes a snapshot of the queue and
the worker registry and returns one :class:`ScalingDecision` — scale up by N, scale down a named
worker, replace an unhealthy one, or do nothing — plus a human-readable reason. It performs no
I/O and has no side effects, so the whole policy is exhaustively unit-tested with plain dicts.

Epics 11b/11c wire this to real Docker control and a ~1–2s control loop; the loop reads the
queue depth and ``JobQueue.list_workers()``, tracks how long the queue has sat quiet, and feeds
all of that here, then carries out whatever this function decides.

Precedence is fixed at **health → up → down**: a single call returns at most one action, checked
in that order, so reaping a dead worker beats growing for load, which beats trimming an idle one.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from app.config import Settings


@dataclass(frozen=True)
class ScalingDecision:
    """One scaling action and the reason for it — the pure output of :func:`decide_scaling`.

    ``action`` is one of ``"scale_up" | "scale_down" | "replace" | "no-op"``; the first three
    mirror the ``ScalingEvent`` vocabulary so Epic 11c can record the decision directly, while
    ``"no-op"`` is the do-nothing result that is never written as a row. ``count`` is how many
    workers to add (set only for ``scale_up``); ``worker_id`` names the worker a ``scale_down``
    or ``replace`` targets (``None`` for fleet-level actions).
    """

    action: str
    reason: str
    count: int = 0
    worker_id: str | None = None


def decide_scaling(
    *,
    queue_depth: int,
    workers: dict[str, dict],
    queue_idle_seconds: int,
    settings: Settings,
    now_ms: int,
) -> ScalingDecision:
    """Decide the single next scaling action from a snapshot of the queue and workers.

    ``workers`` is the ``JobQueue.list_workers()`` shape
    ``{worker_id: {state, current_job, last_heartbeat}}`` (``last_heartbeat`` in epoch ms);
    ``queue_idle_seconds`` is how long the queue has sat at or below ``scale_down_threshold``
    (the control loop tracks this, since the registry alone can't measure idle duration); and
    ``now_ms`` is the current time in epoch ms, used to spot a stale heartbeat.

    Returns a :class:`ScalingDecision`. Phase 1 covers proportional scale-up under the
    ``max_workers`` cap and the no-op fallback; idle scale-down and unhealthy replacement layer
    on in later phases.
    """
    worker_count = len(workers)

    stale_worker_id = _stalest_unhealthy_worker(workers, settings=settings, now_ms=now_ms)
    if stale_worker_id is not None:
        stale_ms = now_ms - workers[stale_worker_id]["last_heartbeat"]
        limit_ms = settings.worker_unhealthy_after_seconds * 1000
        return ScalingDecision(
            action="replace",
            reason=f"{stale_worker_id} heartbeat stale {stale_ms}ms > limit {limit_ms}ms",
            worker_id=stale_worker_id,
        )

    if queue_depth > settings.scale_up_threshold and worker_count < settings.max_workers:
        desired = ceil(queue_depth / settings.scale_up_threshold)
        target = min(desired, settings.max_workers)
        count = target - worker_count
        if count > 0:
            return ScalingDecision(
                action="scale_up",
                reason=(
                    f"queue_depth {queue_depth} > threshold "
                    f"{settings.scale_up_threshold} → +{count}"
                ),
                count=count,
            )

    if (
        queue_depth <= settings.scale_down_threshold
        and queue_idle_seconds >= settings.idle_timeout_seconds
        and worker_count > settings.min_workers
    ):
        idle_worker_id = _first_idle_worker(workers)
        if idle_worker_id is not None:
            return ScalingDecision(
                action="scale_down",
                reason=(
                    f"queue idle {queue_idle_seconds}s ≥ timeout "
                    f"{settings.idle_timeout_seconds}s, {worker_count} > min "
                    f"{settings.min_workers}"
                ),
                worker_id=idle_worker_id,
            )

    return ScalingDecision(action="no-op", reason="queue and workers within thresholds")


def _stalest_unhealthy_worker(
    workers: dict[str, dict], *, settings: Settings, now_ms: int
) -> str | None:
    """The id of the worker with the oldest heartbeat past the unhealthy limit, or ``None``
    if every worker is fresh. Ties break on the lower id so the choice and reason are stable.
    """
    limit_ms = settings.worker_unhealthy_after_seconds * 1000
    stalest_worker_id: str | None = None
    oldest_heartbeat: int | None = None
    for worker_id in sorted(workers):
        last_heartbeat = workers[worker_id].get("last_heartbeat")
        if last_heartbeat is None or now_ms - last_heartbeat <= limit_ms:
            continue
        if oldest_heartbeat is None or last_heartbeat < oldest_heartbeat:
            oldest_heartbeat = last_heartbeat
            stalest_worker_id = worker_id
    return stalest_worker_id


def _first_idle_worker(workers: dict[str, dict]) -> str | None:
    """The lowest-id worker currently ``"idle"``, or ``None`` if none are — picked
    deterministically (sorted by id) so the chosen worker and its reason are stable.
    """
    for worker_id in sorted(workers):
        if workers[worker_id].get("state") == "idle":
            return worker_id
    return None
