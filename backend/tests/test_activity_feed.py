"""Unit tests for the activity-feed service (Epic 10d): line formatting + the ring buffer.

Both pieces are pure and in-memory, so these are plain unit tests — no Redis, no WebSocket. They
pin the readable phrasing for every job state (plus the unknown-state fallback) and that the ring
buffer stays bounded, dropping the oldest line once it is full.
"""

from app.services.activity_feed import ActivityFeed, format_activity_line


def test_running_line_names_worker_and_job():
    line = format_activity_line(
        {"job_id": "job-7", "state": "running", "worker_id": "worker-1", "started_at": 1000}
    )
    assert line == "worker-1 started job-7"


def test_completed_line_names_worker_and_job():
    line = format_activity_line(
        {"job_id": "job-7", "state": "completed", "worker_id": "worker-1", "completed_at": 2000}
    )
    assert line == "worker-1 finished job-7"


def test_failed_line_includes_attempts_and_error():
    line = format_activity_line(
        {"job_id": "job-7", "state": "failed", "attempts": 3, "last_error": "boom"}
    )
    assert line == "job-7 failed after 3 attempts: boom"


def test_failed_line_uses_singular_attempt():
    line = format_activity_line({"job_id": "job-7", "state": "failed", "attempts": 1})
    assert line == "job-7 failed after 1 attempt"


def test_retrying_line_names_attempt_number():
    line = format_activity_line({"job_id": "job-7", "state": "retrying", "attempts": 2})
    assert line == "job-7 retrying (attempt 2)"


def test_queued_line_is_simple():
    line = format_activity_line({"job_id": "job-7", "state": "queued"})
    assert line == "job-7 queued"


def test_sparse_event_falls_back_gracefully():
    # A running event missing its worker still yields a readable line rather than "None started".
    line = format_activity_line({"job_id": "job-7", "state": "running"})
    assert line == "a worker started job-7"


def test_unknown_state_falls_back_to_plain_arrow():
    line = format_activity_line({"job_id": "job-7", "state": "paused"})
    assert line == "job-7 → paused"


def test_line_never_leaks_session_id():
    # session_id rides on every real event; it must never surface in the readable line.
    line = format_activity_line(
        {
            "job_id": "job-7",
            "state": "running",
            "worker_id": "worker-1",
            "session_id": "guest-amber",
        }
    )
    assert "guest-amber" not in line


def test_feed_returns_lines_oldest_first():
    feed = ActivityFeed(max_lines=5)
    feed.record("first")
    feed.record("second")
    assert feed.recent() == ["first", "second"]


def test_feed_is_bounded_and_drops_oldest():
    feed = ActivityFeed(max_lines=3)
    for index in range(5):
        feed.record(f"line-{index}")
    # Only the last three survive; the two oldest were evicted.
    assert feed.recent() == ["line-2", "line-3", "line-4"]


def test_feed_recent_is_a_copy():
    # Mutating the returned list must not disturb the buffer's own state.
    feed = ActivityFeed(max_lines=3)
    feed.record("first")
    snapshot = feed.recent()
    snapshot.append("tampered")
    assert feed.recent() == ["first"]
