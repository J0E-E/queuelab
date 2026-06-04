"""Integration tests for the per-session token bucket (Epic 6), against a real Redis.

These cover the epic's verification points: the bucket allows then denies on schedule, it
refills as time passes, and separate actions/sessions hold separate budgets. Rather than
sleeping out the real 5s/10s intervals, we rewind the bucket's stored ``updated_at_ms`` into
the past (the same time-travel trick the queue tests use on lease scores) so the next check
sees the interval as already elapsed.
"""

import pytest
from app.config import settings
from app.services.guardrails import RateLimitedError
from app.services.rate_limit import RateLimiter, bucket_key


async def _rewind_bucket(redis_client, action: str, session_id: str, milliseconds: int) -> None:
    """Move a bucket's last-update stamp back, so it looks like time has passed."""
    key = bucket_key(action, session_id)
    updated_at_ms = int(await redis_client.hget(key, "updated_at_ms"))
    await redis_client.hset(key, "updated_at_ms", updated_at_ms - milliseconds)


async def test_first_submission_allowed_second_denied(rate_limiter):
    # The first submission is allowed: the check returns without raising.
    assert await rate_limiter.check_submission("session-a") is None

    # The bucket is now empty; an immediate second submission is rejected.
    with pytest.raises(RateLimitedError) as caught:
        await rate_limiter.check_submission("session-a")

    error = caught.value
    assert error.retry_after_seconds == settings.submit_rate_seconds
    assert error.message == f"[WARN] rate limit: 1 submission / {settings.submit_rate_seconds}s"


async def test_bucket_refills_after_the_interval(rate_limiter, redis_client):
    await rate_limiter.check_submission("session-a")
    with pytest.raises(RateLimitedError):
        await rate_limiter.check_submission("session-a")

    # Pretend a full interval has passed; the bucket should have earned its token back.
    await _rewind_bucket(redis_client, "submit", "session-a", settings.submit_rate_seconds * 1000)

    # The bucket refilled, so this submission is allowed again (no raise).
    assert await rate_limiter.check_submission("session-a") is None


async def test_partial_wait_reports_remaining_seconds(rate_limiter, redis_client):
    await rate_limiter.check_submission("session-a")
    # Advance most of the way through the interval — not quite enough for a whole token.
    elapsed_ms = (settings.submit_rate_seconds * 1000) - 1500
    await _rewind_bucket(redis_client, "submit", "session-a", elapsed_ms)

    with pytest.raises(RateLimitedError) as caught:
        await rate_limiter.check_submission("session-a")
    # ~1.5s of wait remains, rounded up to whole seconds.
    assert caught.value.retry_after_seconds == 2


async def test_separate_sessions_have_independent_buckets(rate_limiter):
    await rate_limiter.check_submission("session-a")
    # A different session is unaffected by session-a spending its token.
    assert await rate_limiter.check_submission("session-b") is None


async def test_submit_and_chaos_budgets_are_independent(rate_limiter):
    await rate_limiter.check_submission("session-a")
    # Spending the submit token leaves the chaos bucket untouched.
    assert await rate_limiter.check_chaos("session-a") is None


async def test_chaos_denial_uses_the_chaos_message(rate_limiter):
    await rate_limiter.check_chaos("session-a")
    with pytest.raises(RateLimitedError) as caught:
        await rate_limiter.check_chaos("session-a")

    error = caught.value
    assert error.retry_after_seconds == settings.chaos_rate_seconds
    assert error.message == f"[WARN] rate limit: 1 chaos action / {settings.chaos_rate_seconds}s"


async def test_from_settings_builds_a_working_limiter(redis_url, monkeypatch):
    # Point from_settings at the test container's Redis, then confirm it limits.
    monkeypatch.setattr(settings, "redis_url", redis_url)
    limiter = RateLimiter.from_settings()
    try:
        assert await limiter.check_submission("session-z") is None
        with pytest.raises(RateLimitedError):
            await limiter.check_submission("session-z")
    finally:
        await limiter.aclose()
