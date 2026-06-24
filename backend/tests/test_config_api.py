"""Integration tests for the live config endpoint (Epic 11d-2) against a real Redis.

``GET /api/config`` returns the autoscaler thresholds in force; ``PUT /api/config`` writes a
partial patch validated through the ``Settings`` model. These drive the app through the
``api_client`` fixture, whose ``get_queue`` override points the route at the per-test Redis, so a
PUT round-trips through the same ``ql:config`` hash the autoscaler reads.
"""

from app.config import OVERRIDABLE_CONFIG_KEYS, settings


async def test_get_returns_env_defaults_when_no_override_set(api_client):
    response = await api_client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    # Every overridable key reports its env default — nothing has been overridden yet.
    assert set(body) == set(OVERRIDABLE_CONFIG_KEYS)
    for key in OVERRIDABLE_CONFIG_KEYS:
        assert body[key] == getattr(settings, key)


async def test_put_partial_patch_round_trips_and_leaves_other_keys_at_defaults(api_client):
    response = await api_client.put("/api/config", json={"scale_up_threshold": 8})

    assert response.status_code == 200
    # The patched key is now in force; an untouched key still reads its env default.
    assert response.json()["scale_up_threshold"] == 8
    assert response.json()["max_workers"] == settings.max_workers

    # A fresh GET sees the persisted override too.
    after = (await api_client.get("/api/config")).json()
    assert after["scale_up_threshold"] == 8
    assert after["min_workers"] == settings.min_workers


async def test_put_out_of_bounds_value_is_rejected(api_client):
    # max_workers must be positive; zero fails the Settings field bound.
    response = await api_client.put("/api/config", json={"max_workers": 0})

    assert response.status_code == 422
    assert response.json()["detail"].startswith("[ERR]")
    # Nothing was stored — a later GET still shows the env default.
    assert (await api_client.get("/api/config")).json()["max_workers"] == settings.max_workers


async def test_put_cross_field_violation_is_rejected(api_client):
    # scale_down above scale_up would oscillate the loop — the model validator rejects the merge.
    response = await api_client.put(
        "/api/config", json={"scale_down_threshold": settings.scale_up_threshold + 5}
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("[ERR]")
    assert (await api_client.get("/api/config")).json()[
        "scale_down_threshold"
    ] == settings.scale_down_threshold


async def test_put_unknown_key_is_rejected(api_client):
    # A typo'd / non-overridable key surfaces rather than being silently dropped (extra="forbid").
    response = await api_client.put("/api/config", json={"autoscaler_loop_seconds": 9})

    assert response.status_code == 422
