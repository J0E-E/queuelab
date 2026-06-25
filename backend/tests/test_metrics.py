"""Integration test for GET /api/metrics (Epic 10c, phase 1), against real Redis.

The metrics endpoint returns the queue's aggregate vitals — the live per-state counts plus the
derived ready-queue depth, registered worker count, and how many of those workers are unhealthy
(stale heartbeat). This drives a couple of real jobs and a registered worker into Redis, then
asserts the endpoint's snapshot matches what the queue reports directly.
"""

import json

from app.queue.protocol import WORKERS_KEY


async def test_metrics_snapshot_matches_queue(api_client, queue, make_job):
    # Two jobs enqueued, one claimed (queued -> running), and one registered worker, so the
    # snapshot has non-trivial vitals to report.
    first = make_job(payload={"type": "email", "complexity": 1})
    second = make_job(payload={"type": "report", "complexity": 3})
    await queue.enqueue(first)
    await queue.enqueue(second)
    await queue.claim("worker-1", timeout=5)
    await queue.heartbeat("worker-1", state="busy", current_job=first.id)

    response = await api_client.get("/api/metrics")

    assert response.status_code == 200
    body = response.json()
    # The counts block matches what the queue reports directly.
    assert body["counts"] == await queue.counts()
    assert body["counts"]["queued"] == 1
    assert body["counts"]["running"] == 1
    # One job still waits on the ready queue; one worker is registered and freshly beating.
    assert body["queue_depth"] == 1
    assert body["worker_count"] == 1
    assert body["unhealthy_worker_count"] == 0
    assert body["workers"] == [{"id": "worker-1", "healthy": True, "busy": True}]


async def test_metrics_flags_a_stale_worker_as_unhealthy(api_client, queue, redis_client):
    # A freshly beating worker and one whose heartbeat is long stale (a destroyed/crashed worker
    # not yet reaped). Only the stale one counts as unhealthy, so the grid can paint it as dying.
    now_ms = await queue.now_ms()
    await queue.heartbeat("worker-fresh", state="idle", current_job=None)
    await redis_client.hset(
        WORKERS_KEY,
        "worker-stale",
        json.dumps({"state": "idle", "current_job": None, "last_heartbeat": now_ms - 60_000}),
    )

    response = await api_client.get("/api/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["worker_count"] == 2
    assert body["unhealthy_worker_count"] == 1
    # Per-worker liveness, sorted by id: the fresh one is healthy, the stale one is not.
    assert body["workers"] == [
        {"id": "worker-fresh", "healthy": True, "busy": False},
        {"id": "worker-stale", "healthy": False, "busy": False},
    ]
