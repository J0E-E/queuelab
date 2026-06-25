"""Unit tests for the activity-feed service (Epic 10d): line formatting + the ring buffer.

Both pieces are pure and in-memory, so these are plain unit tests — no Redis, no WebSocket. They
pin the readable phrasing for every job state (plus the unknown-state fallback) and that the ring
buffer stays bounded, dropping the oldest line once it is full.
"""

from app.services.activity_feed import (
    ActivityFeed,
    build_activity_entry,
    current_time_label,
    format_activity_line,
)


def test_running_line_names_worker_and_job():
    parts = format_activity_line(
        {"job_id": "job-7", "state": "running", "worker_id": "worker-1", "started_at": 1000}
    )
    assert parts.action == "worker-1 started job-7"
    assert parts.state == "running"
    assert parts.is_terminal is False


def test_completed_line_names_worker_and_job():
    parts = format_activity_line(
        {"job_id": "job-7", "state": "completed", "worker_id": "worker-1", "completed_at": 2000}
    )
    assert parts.action == "worker-1 finished job-7"


def test_failed_line_includes_attempts_and_error():
    parts = format_activity_line(
        {"job_id": "job-7", "state": "failed", "attempts": 3, "last_error": "boom"}
    )
    assert parts.action == "job-7 failed after 3 attempts: boom"
    assert parts.attempts == 3


def test_failed_line_uses_singular_attempt():
    parts = format_activity_line({"job_id": "job-7", "state": "failed", "attempts": 1})
    assert parts.action == "job-7 failed after 1 attempt"


def test_failed_line_is_terminal_but_retrying_is_not():
    # A `failed` state is only ever published once retries are exhausted, so it is terminal (dead);
    # a `retrying` line is a will-retry failure and must read as not-yet-dead (Epic 17b).
    failed = format_activity_line({"job_id": "job-7", "state": "failed", "attempts": 3})
    retrying = format_activity_line({"job_id": "job-7", "state": "retrying", "attempts": 2})
    assert failed.is_terminal is True
    assert retrying.is_terminal is False


def test_retrying_line_names_attempt_number():
    parts = format_activity_line({"job_id": "job-7", "state": "retrying", "attempts": 2})
    assert parts.action == "job-7 retrying (attempt 2)"
    assert parts.state == "retrying"


def test_queued_line_is_simple():
    parts = format_activity_line({"job_id": "job-7", "state": "queued"})
    assert parts.action == "job-7 queued"


def test_sparse_event_falls_back_gracefully():
    # A running event missing its worker still yields a readable line rather than "None started".
    parts = format_activity_line({"job_id": "job-7", "state": "running"})
    assert parts.action == "a worker started job-7"


def test_unknown_state_falls_back_to_plain_arrow():
    parts = format_activity_line({"job_id": "job-7", "state": "paused"})
    assert parts.action == "job-7 → paused"
    assert parts.is_terminal is False


def test_action_never_leaks_session_id():
    # session_id rides on every real event; it must never surface in the readable action body.
    parts = format_activity_line(
        {
            "job_id": "job-7",
            "state": "running",
            "worker_id": "worker-1",
            "session_id": "guest-amber",
        }
    )
    assert "guest-amber" not in parts.action


def test_entry_carries_structured_parts_and_a_flat_line():
    # The structured entry folds the stamped time and (here unattributed) actor around the parts,
    # and keeps a flat `line` for back-compat / screen readers — the action body when no handle
    # resolved. The live frame is this same entry with a {"type": "activity"} envelope added.
    parts = format_activity_line({"job_id": "job-7", "state": "failed", "attempts": 3})
    entry = build_activity_entry(parts, time="12:04:02")
    assert entry == {
        "time": "12:04:02",
        "handle": None,
        "color": None,
        "action": "job-7 failed after 3 attempts",
        "state": "failed",
        "attempts": 3,
        "is_terminal": True,
        "line": "job-7 failed after 3 attempts",
    }


def test_entry_leads_the_flat_line_with_a_resolved_handle():
    # When an actor resolves, the flat line leads with the handle (so a screen reader hears them).
    parts = format_activity_line({"job_id": "job-7", "state": "running", "worker_id": "worker-1"})
    entry = build_activity_entry(parts, time="00:00:00", handle="guest-teal", color="#2dd4bf")
    assert entry["handle"] == "guest-teal"
    assert entry["color"] == "#2dd4bf"
    assert entry["line"] == "guest-teal worker-1 started job-7"


def test_time_label_is_hh_mm_ss():
    import re

    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", current_time_label())


def test_feed_returns_entries_oldest_first():
    feed = ActivityFeed(max_lines=5)
    feed.record({"line": "first"})
    feed.record({"line": "second"})
    assert feed.recent() == [{"line": "first"}, {"line": "second"}]


def test_feed_is_bounded_and_drops_oldest():
    feed = ActivityFeed(max_lines=3)
    for index in range(5):
        feed.record({"line": f"line-{index}"})
    # Only the last three survive; the two oldest were evicted.
    assert feed.recent() == [{"line": "line-2"}, {"line": "line-3"}, {"line": "line-4"}]


def test_feed_recent_is_a_copy():
    # Mutating the returned list must not disturb the buffer's own state.
    feed = ActivityFeed(max_lines=3)
    feed.record({"line": "first"})
    snapshot = feed.recent()
    snapshot.append({"line": "tampered"})
    assert feed.recent() == [{"line": "first"}]
