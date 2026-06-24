"""Integration tests for the chaos endpoints (Epic 12) against a real Redis.

``POST /api/chaos/inject-failures`` sets a live failure-bias workers read; ``POST
/api/chaos/destroy-worker`` publishes a ``destroy`` command on ``ql:control`` for the autoscaler
to carry out. These drive the app through the ``api_client`` fixture (queue + rate limiter pointed
at the per-test containers), so a call round-trips through the same Redis a worker / the autoscaler
would read.
"""

import asyncio
import json

from app.queue.protocol import CONTROL_CHANNEL


async def _next_message(pubsub):
    """Poll for the next pub/sub frame (subscribe-confirm or message), or None within the window."""
    for _ in range(150):
        message = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.02)
        if message is not None:
            return message
        await asyncio.sleep(0.01)
    return None


async def test_inject_failures_sets_the_bias_and_reports_the_ttl(api_client, queue):
    response = await api_client.post(
        "/api/chaos/inject-failures", json={"session_id": "session-chaos", "bias": 0.7}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bias"] == 0.7
    assert body["ttl_seconds"] > 0
    # The worker-visible key now carries the bias.
    assert await queue.get_failure_bias() == 0.7


async def test_inject_failures_rejects_a_bias_out_of_range(api_client):
    response = await api_client.post(
        "/api/chaos/inject-failures", json={"session_id": "session-bad", "bias": 1.5}
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("[ERR]")


async def test_inject_failures_is_rate_limited(api_client):
    first = await api_client.post(
        "/api/chaos/inject-failures", json={"session_id": "session-fast", "bias": 0.3}
    )
    assert first.status_code == 200

    # A second chaos action from the same session inside the window is throttled.
    second = await api_client.post(
        "/api/chaos/inject-failures", json={"session_id": "session-fast", "bias": 0.3}
    )
    assert second.status_code == 429
    assert second.headers["Retry-After"]


async def test_destroy_worker_publishes_a_destroy_command(api_client, queue, redis_client):
    await queue.heartbeat("worker-x", state="busy", current_job="job-1")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CONTROL_CHANNEL)
    await _next_message(pubsub)  # drain the subscribe-confirmation frame

    response = await api_client.post(
        "/api/chaos/destroy-worker", json={"session_id": "session-d", "worker_id": "worker-x"}
    )

    assert response.status_code == 200
    assert response.json()["worker_id"] == "worker-x"
    message = await _next_message(pubsub)
    assert message is not None
    assert json.loads(message["data"]) == {"command": "destroy", "worker_id": "worker-x"}
    await pubsub.aclose()


async def test_destroy_worker_rejects_an_unregistered_target(api_client, queue):
    # A real worker exists, but the caller names something that is not a registered worker —
    # rejected, so an arbitrary container name (postgres/redis/api) can never be targeted.
    await queue.heartbeat("worker-real", state="idle", current_job=None)
    response = await api_client.post(
        "/api/chaos/destroy-worker", json={"session_id": "session-evil", "worker_id": "postgres"}
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("[WARN]")


async def test_destroy_worker_with_an_empty_fleet_is_409(api_client):
    # No workers registered and no explicit target → nothing to destroy.
    response = await api_client.post(
        "/api/chaos/destroy-worker", json={"session_id": "session-empty"}
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("[WARN]")


async def test_destroy_worker_is_rate_limited(api_client, queue):
    await queue.heartbeat("worker-y", state="idle", current_job=None)
    first = await api_client.post(
        "/api/chaos/destroy-worker", json={"session_id": "session-r", "worker_id": "worker-y"}
    )
    assert first.status_code == 200

    # A second chaos action from the same session inside the window is throttled.
    second = await api_client.post(
        "/api/chaos/destroy-worker", json={"session_id": "session-r", "worker_id": "worker-y"}
    )
    assert second.status_code == 429
