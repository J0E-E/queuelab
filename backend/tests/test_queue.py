"""Integration tests for the custom Redis queue (Epic 3), against a real Redis.

These exercise the epic's verification points: enqueue->claim->ack, a failed job going
nack->retrying->put back on the queue (requeue), recovering a dead worker's job once its
time-limited claim (lease) runs out, running out of retries, and count consistency. Time is
controlled by rewriting the claim/delayed sorted-set scores into the past (then running the
recovery sweep and moving jobs back to ready) rather than sleeping out the real 30s timeout.
"""

import asyncio
import json

import pytest
from app.config import settings as app_settings
from app.queue.protocol import (
    CHAOS_FAILURE_BIAS_KEY,
    CONFIG_KEY,
    CONTROL_CHANNEL,
    DELAYED_KEY,
    LEASES_KEY,
    READY_KEY,
    WORKERS_KEY,
    QueueFullError,
    job_key,
    processing_key,
)

ALL_ZERO_COUNTS = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "retrying": 0}


async def test_enqueue_then_claim_then_ack(queue, redis_client, make_job):
    job = make_job()
    await queue.enqueue(job)

    assert await queue.queue_depth() == 1
    assert (await queue.counts())["queued"] == 1

    claimed = await queue.claim("worker-1", timeout=1)
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.state == "running"
    assert claimed.started_at is not None
    assert claimed.enqueued_at is not None
    assert claimed.worker_id == "worker-1"
    assert await redis_client.zscore(LEASES_KEY, job.id) is not None
    assert await redis_client.lrange(processing_key("worker-1"), 0, -1) == [job.id]
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "running": 1}

    await queue.ack(job.id, "worker-1")
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "completed": 1}
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.lrange(processing_key("worker-1"), 0, -1) == []
    assert await redis_client.hget(job_key(job.id), "state") == "completed"
    # Completed hot record carries the 1h TTL.
    assert await redis_client.ttl(job_key(job.id)) > 0


async def test_nack_retries_via_delayed_then_promotes(queue, redis_client, make_job):
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-1", timeout=1)
    await queue.nack(job.id, "worker-1", "boom")

    assert await redis_client.hget(job_key(job.id), "state") == "retrying"
    assert await redis_client.zscore(DELAYED_KEY, job.id) is not None
    assert await queue.queue_depth() == 0
    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 1
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "retrying": 1}

    # Force the retry wait to have elapsed, then move it back to the active queue (promote).
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})
    assert await queue.promote_due_delayed() == 1
    assert await queue.queue_depth() == 1
    assert await redis_client.hget(job_key(job.id), "state") == "queued"
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "queued": 1}

    reclaimed = await queue.claim("worker-2", timeout=1)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempts == 1


async def test_lease_expiry_requeues_dead_worker_job(queue, redis_client, make_job):
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-A", timeout=1)

    # Worker A "dies": its claim deadline (lease) passes with no ack/nack.
    await redis_client.zadd(LEASES_KEY, {job.id: 0})
    assert await queue.reap_expired_leases() == 1

    # The dead worker's in-flight claim is cleaned up and the job is put back on the queue.
    assert await redis_client.lrange(processing_key("worker-A"), 0, -1) == []
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.hget(job_key(job.id), "worker_id") is None
    assert await redis_client.hget(job_key(job.id), "state") == "retrying"
    assert await redis_client.zscore(DELAYED_KEY, job.id) is not None
    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 1
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "retrying": 1}

    # It can be picked up again by a healthy worker.
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})
    assert await queue.promote_due_delayed() == 1
    reclaimed = await queue.claim("worker-B", timeout=1)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.worker_id == "worker-B"


async def test_stale_ack_nack_from_superseded_worker_is_ignored(queue, redis_client, make_job):
    # A slow worker whose time-limited claim (lease) expired — the recovery sweep (reaper)
    # put the job back on the queue (requeue) and a new worker reclaimed it — must not be
    # able to overwrite the new holder's claim with a late ack/nack.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-slow", timeout=1)

    # worker-slow's claim (lease) runs out; the recovery sweep (reaper) recovers the job,
    # then it's moved back to the active queue (promote).
    await redis_client.zadd(LEASES_KEY, {job.id: 0})
    await queue.reap_expired_leases()
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})
    await queue.promote_due_delayed()

    # A healthy worker reclaims it.
    reclaimed = await queue.claim("worker-fresh", timeout=1)
    assert reclaimed is not None
    assert reclaimed.worker_id == "worker-fresh"
    lease_before = await redis_client.zscore(LEASES_KEY, job.id)

    # The zombie worker-slow now tries to ack and nack — both must do nothing (no-ops).
    await queue.ack(job.id, "worker-slow")
    await queue.nack(job.id, "worker-slow", "late failure")

    assert await redis_client.hget(job_key(job.id), "state") == "running"
    assert await redis_client.hget(job_key(job.id), "worker_id") == "worker-fresh"
    assert await redis_client.zscore(LEASES_KEY, job.id) == lease_before
    assert await redis_client.lrange(processing_key("worker-fresh"), 0, -1) == [job.id]
    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 1
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "running": 1}

    # The real holder can still complete it cleanly.
    await queue.ack(job.id, "worker-fresh")
    assert await redis_client.hget(job_key(job.id), "state") == "completed"
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "completed": 1}


async def test_renew_lease_extends_the_deadline(queue, redis_client, make_job):
    job = make_job()
    await queue.enqueue(job)
    await queue.claim("worker-1", timeout=1)

    # Rewind the lease into the past, as if the deadline were about to pass, then renew it.
    await redis_client.zadd(LEASES_KEY, {job.id: 0})
    await queue.renew_lease(job.id, "worker-1")

    # The deadline jumped forward to roughly now + the visibility timeout (well past "now").
    seconds, _microseconds = await redis_client.time()
    now_ms = seconds * 1000
    new_deadline = await redis_client.zscore(LEASES_KEY, job.id)
    assert new_deadline is not None
    assert new_deadline > now_ms
    # Renewing is not a state change: still running, still owned, counts untouched.
    assert await redis_client.hget(job_key(job.id), "state") == "running"
    assert await redis_client.hget(job_key(job.id), "worker_id") == "worker-1"
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "running": 1}


async def test_renew_lease_from_superseded_worker_is_ignored(queue, redis_client, make_job):
    # A renew from a worker that no longer owns the job must not resurrect its lease.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-slow", timeout=1)

    # worker-slow's claim (lease) expires; the recovery sweep (reaper) requeues the job and
    # clears its owner.
    await redis_client.zadd(LEASES_KEY, {job.id: 0})
    await queue.reap_expired_leases()
    assert await redis_client.zscore(LEASES_KEY, job.id) is None

    # The zombie worker-slow tries to renew — it must be a no-op (no lease re-created).
    await queue.renew_lease(job.id, "worker-slow")
    assert await redis_client.zscore(LEASES_KEY, job.id) is None


async def test_requeue_returns_job_to_ready_without_burning_a_retry(queue, redis_client, make_job):
    # Graceful shutdown hands an in-flight job straight back to the ready queue as `queued`,
    # clearing the claim, and crucially without counting it as a failed attempt.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-1", timeout=1)
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "running": 1}

    await queue.requeue(job.id, "worker-1")

    # Back on the ready queue as `queued`, owner cleared, no retry consumed.
    assert await queue.queue_depth() == 1
    assert await redis_client.hget(job_key(job.id), "state") == "queued"
    assert await redis_client.hget(job_key(job.id), "worker_id") is None
    assert int(await redis_client.hget(job_key(job.id), "attempts")) == 0
    # The in-flight claim (processing list + lease) is gone, and it is not on the delayed set.
    assert await redis_client.lrange(processing_key("worker-1"), 0, -1) == []
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.zscore(DELAYED_KEY, job.id) is None
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "queued": 1}

    # A healthy worker can pick it straight back up.
    reclaimed = await queue.claim("worker-2", timeout=1)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempts == 0


async def test_requeue_from_superseded_worker_is_ignored(queue, redis_client, make_job):
    # A requeue from a worker that no longer owns the job must not disturb the new holder.
    job = make_job(max_retries=2)
    await queue.enqueue(job)
    await queue.claim("worker-slow", timeout=1)

    # worker-slow's claim (lease) expires; the recovery sweep (reaper) requeues the job, it is
    # promoted back to ready, and a fresh worker reclaims it.
    await redis_client.zadd(LEASES_KEY, {job.id: 0})
    await queue.reap_expired_leases()
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})
    await queue.promote_due_delayed()
    reclaimed = await queue.claim("worker-fresh", timeout=1)
    assert reclaimed is not None
    assert reclaimed.worker_id == "worker-fresh"
    lease_before = await redis_client.zscore(LEASES_KEY, job.id)

    # The zombie worker-slow now tries to requeue — it must do nothing.
    await queue.requeue(job.id, "worker-slow")

    assert await redis_client.hget(job_key(job.id), "state") == "running"
    assert await redis_client.hget(job_key(job.id), "worker_id") == "worker-fresh"
    assert await redis_client.zscore(LEASES_KEY, job.id) == lease_before
    assert await redis_client.lrange(processing_key("worker-fresh"), 0, -1) == [job.id]
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "running": 1}


async def test_heartbeat_registers_refreshes_and_deregisters(queue, redis_client):
    # First heartbeat registers the worker; the registry records its state and current job.
    await queue.heartbeat("worker-1", state="busy", current_job="job-abc")
    workers = await queue.list_workers()
    assert set(workers) == {"worker-1"}
    record = workers["worker-1"]
    assert record["state"] == "busy"
    assert record["current_job"] == "job-abc"
    first_heartbeat = record["last_heartbeat"]
    assert isinstance(first_heartbeat, int)

    # Rewind the stored heartbeat into the past, then heartbeat again — last_heartbeat moves
    # forward and the state is updated (registration and refresh are one upsert).
    stale = json.dumps(
        {"state": "busy", "current_job": "job-abc", "last_heartbeat": 0},
        separators=(",", ":"),
    )
    await redis_client.hset(WORKERS_KEY, "worker-1", stale)
    await queue.heartbeat("worker-1", state="idle", current_job=None)
    refreshed = (await queue.list_workers())["worker-1"]
    assert refreshed["state"] == "idle"
    assert refreshed["current_job"] is None
    assert refreshed["last_heartbeat"] > 0

    # Deregister removes the worker entirely (a cleanly stopped worker disappears at once).
    await queue.deregister_worker("worker-1")
    assert await queue.list_workers() == {}


async def test_exhausted_retries_go_failed(queue, redis_client, make_job):
    job = make_job(max_retries=1)
    await queue.enqueue(job)

    # Attempt 1 -> retrying.
    await queue.claim("w1", timeout=1)
    await queue.nack(job.id, "w1", "boom")
    assert await redis_client.hget(job_key(job.id), "state") == "retrying"

    # Attempt 2 exceeds max_retries -> terminal failed.
    await redis_client.zadd(DELAYED_KEY, {job.id: 0})
    await queue.promote_due_delayed()
    await queue.claim("w2", timeout=1)
    await queue.nack(job.id, "w2", "boom again")

    assert await redis_client.hget(job_key(job.id), "state") == "failed"
    assert await queue.queue_depth() == 0
    assert await redis_client.zscore(DELAYED_KEY, job.id) is None
    assert await redis_client.zscore(LEASES_KEY, job.id) is None
    assert await redis_client.lrange(processing_key("w2"), 0, -1) == []
    assert await redis_client.ttl(job_key(job.id)) > 0
    assert await queue.counts() == {**ALL_ZERO_COUNTS, "failed": 1}


async def test_counts_stay_consistent_across_paths(queue, redis_client, make_job):
    # Enqueue-then-claim one job at a time so each worker claims exactly the intended job
    # (the grab-and-move (`BLMOVE`) pops first-in-first-out (FIFO), so claiming by worker
    # after a batch enqueue is ambiguous).

    # completed -> ack
    completed = make_job()
    await queue.enqueue(completed)
    await queue.claim("w-c", timeout=1)
    await queue.ack(completed.id, "w-c")

    # retried -> nack to delayed
    retried = make_job(max_retries=2)
    await queue.enqueue(retried)
    await queue.claim("w-r", timeout=1)
    await queue.nack(retried.id, "w-r", "boom")

    # recovered -> claim (lease) expiry, then the recovery sweep (reap)
    recovered = make_job(max_retries=2)
    await queue.enqueue(recovered)
    await queue.claim("w-x", timeout=1)
    await redis_client.zadd(LEASES_KEY, {recovered.id: 0})
    await queue.reap_expired_leases()

    # failed_now -> immediate failure (no retries left)
    failed_now = make_job(max_retries=0)
    await queue.enqueue(failed_now)
    await queue.claim("w-f", timeout=1)
    await queue.nack(failed_now.id, "w-f", "boom")

    # waiting stays in ready, never claimed.
    await queue.enqueue(make_job())

    # Settle everything: force every delayed job due and move them all back to the active
    # queue (promote).
    delayed_ids = await redis_client.zrange(DELAYED_KEY, 0, -1)
    if delayed_ids:
        await redis_client.zadd(DELAYED_KEY, {member: 0 for member in delayed_ids})
        await queue.promote_due_delayed()

    counts = await queue.counts()
    # Live gauges must equal what's actually in the structures.
    assert counts["queued"] == await redis_client.llen(READY_KEY)
    assert counts["retrying"] == await redis_client.zcard(DELAYED_KEY)
    processing_total = 0
    async for key in redis_client.scan_iter(match="ql:processing:*"):
        processing_total += await redis_client.llen(key)
    assert counts["running"] == processing_total
    # Running lifetime totals for the end states: one completed, one failed.
    assert counts["completed"] == 1
    assert counts["failed"] == 1


async def test_claim_timeout_returns_none(queue, redis_client):
    result = await queue.claim("worker-1", timeout=0.2)
    assert result is None
    assert await queue.counts() == ALL_ZERO_COUNTS
    assert await redis_client.zcard(LEASES_KEY) == 0
    assert await redis_client.llen(processing_key("worker-1")) == 0


async def test_claim_race_two_workers_one_job(queue, redis_client, make_job):
    job = make_job()
    await queue.enqueue(job)

    results = await asyncio.gather(
        queue.claim("worker-A", timeout=1),
        queue.claim("worker-B", timeout=1),
    )
    winners = [record for record in results if record is not None]
    assert len(winners) == 1
    assert winners[0].id == job.id
    # Exactly one claim (lease) and one processing entry exist.
    assert await redis_client.zcard(LEASES_KEY) == 1
    held = await redis_client.llen(processing_key("worker-A"))
    held += await redis_client.llen(processing_key("worker-B"))
    assert held == 1


async def test_enqueue_at_capacity_raises(queue, redis_client, make_job, monkeypatch):
    monkeypatch.setattr(app_settings, "max_total_queued", 2)
    await queue.enqueue(make_job())
    await queue.enqueue(make_job())

    with pytest.raises(QueueFullError):
        await queue.enqueue(make_job())

    # The rejected enqueue left no trace.
    assert await queue.queue_depth() == 2
    assert (await queue.counts())["queued"] == 2


async def test_publish_control_command_round_trips_off_the_channel(queue, redis_client):
    # A command published on ql:control must arrive verbatim to a subscriber on that channel —
    # this is the request side the autoscaler's control consumer (Epic 11d-1) listens on.
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CONTROL_CHANNEL)
    # Drain the subscribe-confirmation frame so what follows is purely the published command.
    await _next_message(pubsub)

    command = {"command": "scale_up", "count": 2}
    await queue.publish_control_command(command)

    message = await _next_message(pubsub)
    assert message is not None
    assert json.loads(message["data"]) == command
    await pubsub.aclose()


async def _next_message(pubsub):
    """Poll for the next pub/sub frame (subscribe-confirm or message), or None within the window."""
    for _ in range(150):
        message = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.02)
        if message is not None:
            return message
        await asyncio.sleep(0.01)
    return None


async def test_config_overrides_round_trip(queue):
    # An empty ql:config reads back as no overrides.
    assert await queue.get_config() == {}

    # A partial patch writes only the given keys; get_config decodes them back to ints.
    await queue.set_config({"scale_up_threshold": 8, "max_workers": 6})
    assert await queue.get_config() == {"scale_up_threshold": 8, "max_workers": 6}


async def test_set_config_is_a_partial_patch(queue, redis_client):
    await queue.set_config({"scale_up_threshold": 8, "max_workers": 6})

    # A second patch overwrites only its own keys, leaving the untouched override in place.
    await queue.set_config({"scale_up_threshold": 9})
    assert await queue.get_config() == {"scale_up_threshold": 9, "max_workers": 6}

    # An empty patch is a no-op (does not clear the hash).
    await queue.set_config({})
    assert await redis_client.hgetall(CONFIG_KEY) != {}


async def test_failure_bias_round_trips_with_a_ttl(queue, redis_client):
    # No bias set yet reads back as zero (normal failure rates).
    assert await queue.get_failure_bias() == 0.0

    # Setting a bias stores the value and an expiry, so the injection self-decays.
    await queue.set_failure_bias(0.5, ttl_seconds=30)
    assert await queue.get_failure_bias() == 0.5
    assert 0 < await redis_client.ttl(CHAOS_FAILURE_BIAS_KEY) <= 30


async def test_scripts_reload_after_flush(queue, redis_client, make_job):
    # A Redis SCRIPT FLUSH (or restart) must not break the client — EVALSHA falls back
    # to SCRIPT LOAD on NOSCRIPT automatically.
    job = make_job()
    await queue.enqueue(job)
    await redis_client.script_flush()

    claimed = await queue.claim("worker-1", timeout=1)
    assert claimed is not None
    await queue.ack(job.id, "worker-1")
    assert await redis_client.hget(job_key(job.id), "state") == "completed"
