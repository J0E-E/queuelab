"""Integration tests for the session endpoint (Epic 7 review) against real Redis.

``POST /api/session`` mints a guest identity, binds it server-side so a later submission can
trust the session id, and is throttled per client IP so a caller can't rotate fresh sessions
faster than it could submit. Driven through the ``api_client`` fixture, which presents a
stable peer IP, so a second immediate call from the same IP trips the limit.
"""


async def test_create_session_binds_identity_server_side(api_client, session_store):
    response = await api_client.post("/api/session")

    assert response.status_code == 200
    body = response.json()
    # The minted handle is recorded under its session id, so submit_batch can derive it.
    assert await session_store.get_handle(body["session_id"]) == body["guest_handle"]


async def test_get_identity_returns_the_handle_and_color(api_client, session_store):
    # The activity feed (Epic 17b) resolves both the handle and its color from the session id,
    # server-side, to attribute and tint a guest's lines.
    response = await api_client.post("/api/session")
    body = response.json()

    identity = await session_store.get_identity(body["session_id"])
    assert identity == {"handle": body["guest_handle"], "color": body["color"]}


async def test_get_identity_is_none_for_an_unknown_session(session_store):
    # An expired or never-issued session resolves to nothing, so its line stays unattributed.
    assert await session_store.get_identity("never-issued") is None


async def test_create_session_is_rate_limited_per_ip(api_client):
    first = await api_client.post("/api/session")
    assert first.status_code == 200

    # The immediate second mint from the same IP is throttled.
    second = await api_client.post("/api/session")
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert second.json()["detail"].startswith("[WARN] rate limit: 1 session")
