"""Integration test for GET /api/metrics (Epic 10c, phase 1), against real Redis.

The metrics endpoint returns the queue's aggregate vitals — the live per-state counts plus the
derived ready-queue depth and registered worker count. This drives a couple of real jobs and a
registered worker into Redis, then asserts the endpoint's snapshot matches what the queue
reports directly.
"""


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
    # One job still waits on the ready queue; one worker is registered.
    assert body["queue_depth"] == 1
    assert body["worker_count"] == 1
