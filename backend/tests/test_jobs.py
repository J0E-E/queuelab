"""Integration tests for the job endpoints (Epic 7) against real Redis + Postgres.

``POST /api/jobs`` is exercised end to end: a happy-path batch is checked to land both in
Postgres (durable rows) and on the Redis ready queue (runnable ids), and each guardrail path
(over cap, bad type, bad complexity, rate limited, at capacity) is checked for its status code
and system-voice message. ``GET /api/jobs`` is exercised for paging and the session/state
filters, seeding rows directly so the per-session rate limit doesn't get in the way.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.models.job import Job
from app.queue.protocol import READY_KEY, JobState, job_key
from app.services.identity import GuestIdentity
from sqlalchemy import func, select

# A valid batch body; tests copy it and tweak the field under test. Identity is just the
# session_id now — the guest_handle is derived server-side from the stored session.
VALID_BODY = {
    "session_id": "session-abc",
    "count": 5,
    "type": "email",
    "complexity": 3,
}


def _body(**overrides):
    """Return a copy of the valid submission body with the given fields replaced."""
    return {**VALID_BODY, **overrides}


async def _register_session(
    session_store, session_id="session-abc", guest_handle="guest-pink", color="#ff5fd2"
):
    """Persist a guest session so a submission can derive its trusted handle, as the real
    ``POST /api/session`` would have done first."""
    await session_store.save(
        GuestIdentity(session_id=session_id, guest_handle=guest_handle, color=color)
    )


async def _count_jobs(database) -> int:
    """Count every durable job row currently in Postgres."""
    async with database.session() as session:
        return await session.scalar(select(func.count()).select_from(Job))


def _seed_job(**overrides) -> Job:
    """Build one durable ``Job`` row with sensible defaults for the read-back tests."""
    defaults = {
        "id": uuid.uuid4(),
        "session_id": "session-abc",
        "guest_handle": "guest-pink",
        "type": "email",
        "complexity": 1,
        "max_retries": 3,
        "retry_delay_ms": 2000,
        "state": JobState.QUEUED.value,
        "attempts": 0,
        "submitted_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Job(**defaults)


# ---- POST /api/jobs --------------------------------------------------------------------


async def test_submit_batch_persists_rows_and_enqueues_ids(
    api_client, database, redis_client, session_store
):
    await _register_session(session_store)
    response = await api_client.post("/api/jobs", json=_body(count=5))

    assert response.status_code == 201
    payload = response.json()
    assert payload["accepted"] == 5
    assert payload["batch_id"]  # a non-empty correlation id

    # Five ids landed on the ready queue, and each has a hot record behind it.
    ready_ids = await redis_client.lrange(READY_KEY, 0, -1)
    assert len(ready_ids) == 5
    for ready_id in ready_ids:
        assert await redis_client.exists(job_key(ready_id))

    # Five durable rows were committed, and each shares its id with a queued record.
    assert await _count_jobs(database) == 5
    async with database.session() as session:
        for ready_id in ready_ids:
            row = await session.get(Job, uuid.UUID(ready_id))
            assert row is not None
            assert row.type == "email"
            assert row.complexity == 3
            assert row.state == JobState.QUEUED.value
            assert row.guest_handle == "guest-pink"


async def test_submit_fills_default_retry_settings(api_client, database, session_store):
    await _register_session(session_store)
    # The body omits max_retries / retry_delay_ms, so the configured defaults are used.
    await api_client.post("/api/jobs", json=_body(count=1))

    async with database.session() as session:
        row = await session.scalar(select(Job))
    assert row.max_retries == settings.default_max_retries
    assert row.retry_delay_ms == settings.default_retry_delay_ms


async def test_submit_honors_custom_retry_settings(api_client, database, session_store):
    await _register_session(session_store)
    await api_client.post("/api/jobs", json=_body(count=1, max_retries=1, retry_delay_ms=100))

    async with database.session() as session:
        row = await session.scalar(select(Job))
    assert row.max_retries == 1
    assert row.retry_delay_ms == 100


async def test_submit_over_count_cap_returns_422(api_client, database):
    cap = settings.max_jobs_per_submission
    response = await api_client.post("/api/jobs", json=_body(count=cap + 1))

    assert response.status_code == 422
    assert response.json()["detail"] == f"[ERR] --count exceeds cap (max {cap})"
    # Nothing was written for a rejected batch.
    assert await _count_jobs(database) == 0


async def test_submit_unknown_type_returns_422(api_client):
    response = await api_client.post("/api/jobs", json=_body(type="spam"))

    assert response.status_code == 422
    assert response.json()["detail"].startswith("[ERR] --type must be one of")


async def test_submit_out_of_range_complexity_returns_422(api_client):
    response = await api_client.post("/api/jobs", json=_body(complexity=9))

    assert response.status_code == 422
    assert response.json()["detail"] == "[ERR] --complexity must be between 1 and 5"


async def test_submit_out_of_range_retries_returns_422(api_client, database):
    # An out-of-range retry override is rejected up front, never reaching the durable columns.
    response = await api_client.post("/api/jobs", json=_body(max_retries=99))

    assert response.status_code == 422
    assert response.json()["detail"] == "[ERR] --max-retries must be between 0 and 10"
    assert await _count_jobs(database) == 0


async def test_submit_unknown_session_returns_422(api_client, database):
    # A session_id with no stored identity is rejected before any work; nothing is written.
    response = await api_client.post("/api/jobs", json=_body(count=1, session_id="session-ghost"))

    assert response.status_code == 422
    assert response.json()["detail"] == "[ERR] unknown or expired session — refresh the page"
    assert await _count_jobs(database) == 0


async def test_submit_twice_is_rate_limited_429(api_client, session_store):
    await _register_session(session_store, session_id="session-fast")
    # First submission for this session is allowed; the immediate second trips the limit.
    first = await api_client.post("/api/jobs", json=_body(count=1, session_id="session-fast"))
    assert first.status_code == 201

    second = await api_client.post("/api/jobs", json=_body(count=1, session_id="session-fast"))
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert second.json()["detail"].startswith("[WARN] rate limit")


async def test_submit_at_capacity_returns_409(api_client, redis_client, database, session_store):
    await _register_session(session_store)
    # Fill the ready list to the system-wide cap, so one more job has no room.
    placeholder_ids = [f"job-{index}" for index in range(settings.max_total_queued)]
    await redis_client.rpush(READY_KEY, *placeholder_ids)

    response = await api_client.post("/api/jobs", json=_body(count=1))

    assert response.status_code == 409
    assert response.json()["detail"] == "[ERR] queue at capacity"
    # The rejected batch wrote no durable rows.
    assert await _count_jobs(database) == 0


# ---- GET /api/jobs ---------------------------------------------------------------------


async def test_list_jobs_returns_paged_envelope(api_client, database):
    # Seed three rows with increasing submission times so "newest first" is predictable.
    base = datetime.now(UTC)
    rows = [_seed_job(submitted_at=base + timedelta(seconds=index)) for index in range(3)]
    async with database.session() as session:
        session.add_all(rows)
        await session.commit()

    response = await api_client.get("/api/jobs", params={"limit": 2, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 0
    assert len(payload["items"]) == 2
    # Newest first: the last-seeded row leads the page.
    assert payload["items"][0]["id"] == str(rows[2].id)
    # session_id is deliberately not exposed (it's the rate-limit / identity key); the
    # public-facing guest_handle is.
    assert "session_id" not in payload["items"][0]
    assert payload["items"][0]["guest_handle"] == "guest-pink"


async def test_list_jobs_filters_by_session_and_state(api_client, database):
    async with database.session() as session:
        session.add_all(
            [
                _seed_job(session_id="session-a", state=JobState.COMPLETED.value),
                _seed_job(session_id="session-a", state=JobState.QUEUED.value),
                _seed_job(session_id="session-b", state=JobState.COMPLETED.value),
            ]
        )
        await session.commit()

    by_session = await api_client.get("/api/jobs", params={"session": "session-a"})
    assert by_session.json()["total"] == 2

    by_session_and_state = await api_client.get(
        "/api/jobs", params={"session": "session-a", "state": "completed"}
    )
    assert by_session_and_state.json()["total"] == 1


async def test_list_jobs_unknown_state_is_empty(api_client, database):
    async with database.session() as session:
        session.add(_seed_job())
        await session.commit()

    response = await api_client.get("/api/jobs", params={"state": "nonsense"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []


async def test_list_jobs_clamps_limit_to_ceiling(api_client):
    # An over-large limit is clamped to the hard ceiling rather than honoured.
    response = await api_client.get("/api/jobs", params={"limit": 9999})

    assert response.status_code == 200
    assert response.json()["limit"] == 200


async def test_list_jobs_clamps_offset_to_ceiling(api_client):
    # An over-deep offset is clamped to the hard ceiling rather than honoured.
    response = await api_client.get("/api/jobs", params={"offset": 99999})

    assert response.status_code == 200
    assert response.json()["offset"] == 10000
