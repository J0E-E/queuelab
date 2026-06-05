"""Unit tests for the scaling-policy core (Epic 11a): the pure ``decide_scaling`` function.

The policy does no I/O — it takes a snapshot of the queue depth and worker registry and returns
one decision — so these are plain unit tests: real ``Settings`` built in-process, plain dicts for
the registry, no Redis/Postgres/Docker. They pin proportional scale-up under the ``max_workers``
cap, idle scale-down under the ``min_workers`` floor, stale-heartbeat replacement, and the
health → up → down precedence between them.
"""

from app.config import Settings
from app.services.autoscaler import ScalingDecision, decide_scaling


def make_settings(**overrides) -> Settings:
    """A Settings instance with autoscaler-relevant defaults, overridable per test."""
    defaults = {
        "min_workers": 1,
        "max_workers": 10,
        "scale_up_threshold": 5,
        "scale_down_threshold": 1,
        "idle_timeout_seconds": 30,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_workers(*, idle: int = 0, busy: int = 0) -> dict[str, dict]:
    """A registry of fresh-heartbeat workers: ``idle`` idle ones then ``busy`` busy ones."""
    workers: dict[str, dict] = {}
    for index in range(idle):
        workers[f"worker-idle-{index}"] = {
            "state": "idle",
            "current_job": None,
            "last_heartbeat": 1_000_000,
        }
    for index in range(busy):
        workers[f"worker-busy-{index}"] = {
            "state": "busy",
            "current_job": f"job-{index}",
            "last_heartbeat": 1_000_000,
        }
    return workers


def decide(*, queue_depth, workers, queue_idle_seconds=0, settings=None, now_ms=1_000_000):
    """Call decide_scaling with test defaults so each test sets only what it cares about."""
    return decide_scaling(
        queue_depth=queue_depth,
        workers=workers,
        queue_idle_seconds=queue_idle_seconds,
        settings=settings or make_settings(),
        now_ms=now_ms,
    )


# ---- Phase 1: proportional scale-up + no-op ----


def test_scales_up_when_queue_exceeds_threshold():
    decision = decide(queue_depth=20, workers=make_workers(busy=1))
    assert decision.action == "scale_up"
    # ceil(20 / 5) = 4 desired, minus the 1 running worker = +3.
    assert decision.count == 3


def test_scale_up_count_is_proportional_to_depth():
    decision = decide(queue_depth=40, workers=make_workers(busy=2))
    # ceil(40 / 5) = 8 desired, minus 2 running = +6.
    assert decision.count == 6


def test_scale_up_is_clamped_to_max_workers():
    decision = decide(
        queue_depth=500, workers=make_workers(busy=2), settings=make_settings(max_workers=10)
    )
    assert decision.action == "scale_up"
    # ceil(500 / 5) = 100 desired, clamped to max_workers 10, minus 2 running = +8.
    assert decision.count == 8


def test_no_op_at_the_max_workers_cap():
    decision = decide(
        queue_depth=500, workers=make_workers(busy=10), settings=make_settings(max_workers=10)
    )
    assert decision.action == "no-op"


def test_no_op_when_queue_is_at_or_below_scale_up_threshold():
    decision = decide(queue_depth=5, workers=make_workers(busy=1))
    assert decision.action == "no-op"


def test_scale_up_reason_quotes_depth_and_threshold():
    decision = decide(queue_depth=20, workers=make_workers(busy=1))
    assert "queue_depth 20" in decision.reason
    assert "threshold 5" in decision.reason


def test_decision_is_immutable():
    decision = ScalingDecision(action="no-op", reason="x")
    try:
        decision.action = "scale_up"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ScalingDecision should be frozen")


# ---- Phase 2: idle scale-down (named worker) ----


def test_scales_down_an_idle_worker_when_queue_quiet_past_timeout():
    decision = decide(
        queue_depth=0,
        workers=make_workers(idle=3),
        queue_idle_seconds=40,
    )
    assert decision.action == "scale_down"
    assert decision.worker_id == "worker-idle-0"


def test_holds_scale_down_before_idle_timeout_elapses():
    decision = decide(
        queue_depth=0,
        workers=make_workers(idle=3),
        queue_idle_seconds=10,
    )
    assert decision.action == "no-op"


def test_holds_scale_down_at_the_min_workers_floor():
    decision = decide(
        queue_depth=0,
        workers=make_workers(idle=1),
        queue_idle_seconds=40,
        settings=make_settings(min_workers=1),
    )
    assert decision.action == "no-op"


def test_no_scale_down_when_no_worker_is_idle():
    # Above the floor and quiet, but every worker is busy — nothing safe to remove.
    decision = decide(
        queue_depth=0,
        workers=make_workers(busy=3),
        queue_idle_seconds=40,
    )
    assert decision.action == "no-op"


def test_scale_up_wins_over_scale_down_when_both_could_apply():
    # A deep queue with idle workers: load beats trimming (up-over-down precedence).
    decision = decide(
        queue_depth=50,
        workers=make_workers(idle=2),
        queue_idle_seconds=40,
    )
    assert decision.action == "scale_up"


# ---- Phase 3: unhealthy detection (replace) + precedence ----


def worker_with_heartbeat(heartbeat_ms: int, *, state: str = "busy") -> dict:
    """A single worker record stamped with a given last_heartbeat."""
    return {"state": state, "current_job": None, "last_heartbeat": heartbeat_ms}


def test_replaces_a_worker_whose_heartbeat_is_stale():
    decision = decide(
        queue_depth=0,
        workers={"worker-1": worker_with_heartbeat(1_000_000)},
        now_ms=1_000_000 + 20_000,  # 20s stale, past the 15s limit
    )
    assert decision.action == "replace"
    assert decision.worker_id == "worker-1"


def test_fresh_workers_are_not_replaced():
    decision = decide(
        queue_depth=0,
        workers={"worker-1": worker_with_heartbeat(1_000_000)},
        now_ms=1_000_000 + 10_000,  # 10s old, within the 15s limit
    )
    assert decision.action == "no-op"


def test_staleness_boundary_is_exclusive():
    # Exactly at the limit is still healthy; one ms past it tips into unhealthy.
    at_limit = decide(
        queue_depth=0,
        workers={"worker-1": worker_with_heartbeat(1_000_000)},
        now_ms=1_000_000 + 15_000,
    )
    assert at_limit.action == "no-op"
    past_limit = decide(
        queue_depth=0,
        workers={"worker-1": worker_with_heartbeat(1_000_000)},
        now_ms=1_000_000 + 15_001,
    )
    assert past_limit.action == "replace"


def test_replace_picks_the_stalest_worker():
    decision = decide(
        queue_depth=0,
        workers={
            "worker-1": worker_with_heartbeat(1_000_000 + 5_000),
            "worker-2": worker_with_heartbeat(1_000_000),  # the oldest heartbeat
        },
        now_ms=1_000_000 + 30_000,
    )
    assert decision.action == "replace"
    assert decision.worker_id == "worker-2"


def test_replace_wins_over_a_deep_queue():
    # Health beats load: a stale worker is replaced even with the queue far above threshold.
    decision = decide(
        queue_depth=500,
        workers={"worker-1": worker_with_heartbeat(1_000_000)},
        now_ms=1_000_000 + 30_000,
    )
    assert decision.action == "replace"
