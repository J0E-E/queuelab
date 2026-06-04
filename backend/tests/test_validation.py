"""Tests for submission validation: caps (unit) and capacity (real Redis) — Epic 6.

The cap check is pure, so most of this is plain unit testing of the boundaries. The capacity
check reads the live queue depth, so it runs against the real Redis queue fixture with the
ready list stuffed up to the cap.
"""

import pytest
from app.config import settings
from app.queue.protocol import READY_KEY, JobType, QueueFullError
from app.services.guardrails import InvalidSubmissionError
from app.services.validation import (
    ensure_within_capacity,
    validate_complexity,
    validate_job_type,
    validate_retry_settings,
    validate_submission_count,
)


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


def test_every_known_type_passes():
    # Each canonical job type is accepted (no exception).
    for kind in JobType:
        validate_job_type(kind.value)


def test_unknown_type_is_rejected():
    with pytest.raises(InvalidSubmissionError) as caught:
        validate_job_type("spam")
    assert caught.value.message.startswith("[ERR] --type must be one of")


def test_complexity_within_range_passes():
    # The 1 and 5 endpoints are both valid.
    validate_complexity(1)
    validate_complexity(5)


@pytest.mark.parametrize("bad_value", [0, 6])
def test_complexity_out_of_range_is_rejected(bad_value):
    with pytest.raises(InvalidSubmissionError) as caught:
        validate_complexity(bad_value)
    assert caught.value.message == "[ERR] --complexity must be between 1 and 5"


def test_retry_settings_within_range_pass():
    # Omitted (None) and in-range values are both accepted; None means "use the default".
    validate_retry_settings(None, None)
    validate_retry_settings(0, 0)
    validate_retry_settings(10, 60000)


@pytest.mark.parametrize("bad_value", [-1, 11])
def test_max_retries_out_of_range_is_rejected(bad_value):
    with pytest.raises(InvalidSubmissionError) as caught:
        validate_retry_settings(bad_value, None)
    assert caught.value.message == "[ERR] --max-retries must be between 0 and 10"


@pytest.mark.parametrize("bad_value", [-1, 60001])
def test_retry_delay_out_of_range_is_rejected(bad_value):
    with pytest.raises(InvalidSubmissionError) as caught:
        validate_retry_settings(None, bad_value)
    assert caught.value.message == "[ERR] --retry-delay-ms must be between 0 and 60000"


async def test_capacity_check_passes_with_room(queue):
    # An empty queue is well under the cap, so this returns without raising.
    await ensure_within_capacity(queue)


async def test_capacity_check_rejects_at_cap(queue, redis_client):
    # Fill the ready list to the system-wide cap with placeholder ids.
    job_ids = [f"job-{index}" for index in range(settings.max_total_queued)]
    await redis_client.rpush(READY_KEY, *job_ids)

    with pytest.raises(QueueFullError):
        await ensure_within_capacity(queue)


async def test_capacity_check_rejects_when_batch_would_overflow(queue, redis_client):
    # One short of the cap, but a batch of two has no room — the batch size is what counts.
    job_ids = [f"job-{index}" for index in range(settings.max_total_queued - 1)]
    await redis_client.rpush(READY_KEY, *job_ids)

    with pytest.raises(QueueFullError):
        await ensure_within_capacity(queue, count=2)
