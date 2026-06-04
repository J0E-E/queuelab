"""Tests for submission validation: caps (unit) and capacity (real Redis) — Epic 6.

The cap check is pure, so most of this is plain unit testing of the boundaries. The capacity
check reads the live queue depth, so it runs against the real Redis queue fixture with the
ready list stuffed up to the cap.
"""

import pytest
from app.config import settings
from app.queue.protocol import READY_KEY, QueueFullError
from app.services.guardrails import InvalidSubmissionError
from app.services.validation import ensure_within_capacity, validate_submission_count


def test_count_within_cap_passes():
    # A normal batch and the exact cap are both fine (no exception).
    validate_submission_count(1)
    validate_submission_count(settings.max_jobs_per_submission)


def test_count_above_cap_is_rejected():
    cap = settings.max_jobs_per_submission
    with pytest.raises(InvalidSubmissionError) as caught:
        validate_submission_count(cap + 1)
    assert caught.value.message == f"[ERR] --count exceeds cap (max {cap})"


def test_count_below_one_is_rejected():
    with pytest.raises(InvalidSubmissionError) as caught:
        validate_submission_count(0)
    assert caught.value.message == "[ERR] --count must be at least 1"


async def test_capacity_check_passes_with_room(queue):
    # An empty queue is well under the cap, so this returns without raising.
    await ensure_within_capacity(queue)


async def test_capacity_check_rejects_at_cap(queue, redis_client):
    # Fill the ready list to the system-wide cap with placeholder ids.
    job_ids = [f"job-{index}" for index in range(settings.max_total_queued)]
    await redis_client.rpush(READY_KEY, *job_ids)

    with pytest.raises(QueueFullError):
        await ensure_within_capacity(queue)
