"""Integration test for the WS /ws snapshot-on-connect (Epic 10b, phase 1), against real Redis.

A browser that connects to ``/ws`` must immediately receive a ``snapshot`` frame describing the
current queue state — the live counts plus the in-flight jobs — so a late-joiner sees the grid
seeded rather than empty. This drives a couple of real jobs into Redis, connects, and asserts
the opening frame. It also pins the privacy contract: ``session_id`` never appears in the
broadcast projection.
"""

from httpx_ws import aconnect_ws


async def test_ws_sends_snapshot_on_connect(queue, connection_manager, ws_app_client, make_job):
    # Seed two jobs, then claim one so the snapshot spans both a queued and a running job.
    first = make_job(payload={"type": "email", "complexity": 1})
    second = make_job(payload={"type": "report", "complexity": 3})
    await queue.enqueue(first)
    await queue.enqueue(second)
    await queue.claim("worker-1", timeout=5)

    async with ws_app_client() as client, aconnect_ws("http://test/ws", client) as websocket:
        snapshot = await websocket.receive_json()

    assert snapshot["type"] == "snapshot"
    # One job moved queued -> running on the claim; the other still waits.
    assert snapshot["counts"]["queued"] == 1
    assert snapshot["counts"]["running"] == 1

    jobs_by_id = {job["job_id"]: job for job in snapshot["jobs"]}
    assert {first.id, second.id} <= set(jobs_by_id)
    # The claimed job carries its worker and running state; both job types survive the projection.
    states = {job["state"] for job in snapshot["jobs"]}
    assert states == {"queued", "running"}
    assert {job["type"] for job in snapshot["jobs"]} == {"email", "report"}

    # The rate-limit key must never reach a broadcast frame.
    for job in snapshot["jobs"]:
        assert "session_id" not in job
