"""Tests for the autoscaler control loop (Epic 11c): the tick, idle tracking, and execution.

The policy (Epic 11a) and the Docker wrapper (Epic 11b) are already tested in isolation; these
tests cover the loop that ties them together. ``IdleTracker`` is pure, so it is unit-tested with
plain integers. The tick runs against a real Redis (testcontainers) seeded through
``queue.heartbeat`` so the registry the policy reads is genuine, with a **fake DockerControl** that
records start/kill calls instead of touching a daemon — no Docker required.
"""

from __future__ import annotations

from app.autoscaler_main import IdleTracker, _run_one_tick
from app.config import Settings, settings
from app.models.scaling_event import ScalingEvent
from app.queue.protocol import READY_KEY
from sqlalchemy import select


class FakeDockerControl:
    """A stand-in DockerControl that records what the loop asked it to do, no daemon needed."""

    def __init__(self) -> None:
        self.started = 0
        self.killed: list[str] = []

    def start_worker(self) -> None:
        self.started += 1

    def kill_worker(self, worker_id: str) -> None:
        self.killed.append(worker_id)

    def list_workers(self) -> list[None]:
        """Stand in for the running containers: every start that hasn't since been killed.

        The loop clamps scale-up against this running count (not the registry) to hold the hard
        cap despite registration lag, so the fake must expose it.
        """
        return [None] * (self.started - len(self.killed))


async def _seed_worker(queue, worker_id: str, *, state: str = "idle") -> None:
    """Register a worker in ``ql:workers`` with a fresh heartbeat, as a live worker would."""
    await queue.heartbeat(worker_id, state=state, current_job=None)


async def _scaling_events(database) -> list[ScalingEvent]:
    """Every recorded scaling_event row, oldest first."""
    async with database.session() as session:
        result = await session.execute(select(ScalingEvent).order_by(ScalingEvent.id))
        return list(result.scalars())


# ---- IdleTracker (pure) ---------------------------------------------------------------


def test_idle_tracker_reports_zero_while_the_queue_is_busy():
    tracker = IdleTracker()
    # Depth above the threshold is "busy" — never idle, no streak.
    assert tracker.update(10, now_ms=1_000, threshold=1) == 0
    assert tracker.update(10, now_ms=9_000, threshold=1) == 0


def test_idle_tracker_counts_the_continuous_quiet_stretch():
    tracker = IdleTracker()
    # First quiet tick stamps the start and reads zero elapsed.
    assert tracker.update(0, now_ms=1_000, threshold=1) == 0
    # Five seconds later, still quiet — five whole seconds idle.
    assert tracker.update(1, now_ms=6_000, threshold=1) == 5


def test_idle_tracker_resets_when_the_queue_gets_busy_again():
    tracker = IdleTracker()
    tracker.update(0, now_ms=1_000, threshold=1)
    # A busy tick clears the streak...
    assert tracker.update(5, now_ms=4_000, threshold=1) == 0
    # ...so the next quiet stretch starts counting fresh from here, not from the first lull.
    assert tracker.update(0, now_ms=5_000, threshold=1) == 0
    assert tracker.update(0, now_ms=8_000, threshold=1) == 3


# ---- The tick: execution per decision (real Redis, fake Docker) -----------------------


async def test_tick_scales_up_one_container_per_count(queue, redis_client, database, make_job):
    docker_control = FakeDockerControl()
    # No workers and a flood well past the scale-up threshold → the policy asks for several.
    for _ in range(settings.scale_up_threshold * 2):
        await queue.enqueue(make_job())

    decision = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )

    assert decision.action == "scale_up"
    assert docker_control.started == decision.count
    assert docker_control.killed == []
    # One audit row, counting up from zero workers by the decided amount.
    (event,) = await _scaling_events(database)
    assert event.action == "scale_up"
    assert event.worker_count_after == decision.count


async def test_tick_does_not_spawn_past_the_cap_when_running_workers_have_not_registered_yet(
    queue, redis_client, database, make_job
):
    docker_control = FakeDockerControl()
    # Simulate a prior tick that already spawned a full fleet which hasn't registered yet: the
    # containers are running (list_workers) but absent from the registry the policy reads.
    docker_control.started = settings.max_workers
    for _ in range(settings.scale_up_threshold * 2):
        await queue.enqueue(make_job())

    decision = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )

    # The registry shows zero, so the policy wants to scale up, but the running count is already at
    # the cap — the clamp suppresses it rather than overshooting.
    assert decision.action == "no-op"
    assert docker_control.started == settings.max_workers
    assert await _scaling_events(database) == []


async def test_tick_no_op_touches_nothing_and_writes_no_row(queue, redis_client, database):
    docker_control = FakeDockerControl()
    # Empty queue, one worker at the floor — nothing to do.
    await _seed_worker(queue, "worker-1")

    decision = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )

    assert decision.action == "no-op"
    assert docker_control.started == 0
    assert docker_control.killed == []
    # A no-op is never written as a row.
    assert await _scaling_events(database) == []


async def test_tick_scales_down_kills_and_deregisters_an_idle_worker(queue, redis_client, database):
    docker_control = FakeDockerControl()
    # Two idle workers above the floor and an empty queue that has sat quiet past idle_timeout.
    await _seed_worker(queue, "worker-1")
    await _seed_worker(queue, "worker-2")
    now_ms = await queue.now_ms()
    tracker = IdleTracker()
    # Prime the streak so this single tick already sees the queue as long-idle (past the timeout).
    tracker.update(0, now_ms=now_ms - 100_000, threshold=settings.scale_down_threshold)

    decision = await _run_one_tick(queue, docker_control, tracker, database, settings=settings)

    assert decision.action == "scale_down"
    assert decision.worker_id == "worker-1"  # lowest id — the deterministic pick
    assert docker_control.killed == ["worker-1"]
    assert docker_control.started == 0
    # The scaled-down worker is gone from the registry; the survivor remains.
    assert set((await queue.list_workers()).keys()) == {"worker-2"}
    # One audit row: two workers minus the one trimmed.
    (event,) = await _scaling_events(database)
    assert event.action == "scale_down"
    assert event.worker_id == "worker-1"
    assert event.worker_count_after == 1


async def test_tick_replaces_kills_deregisters_and_starts_a_fresh_worker(
    queue, redis_client, database
):
    docker_control = FakeDockerControl()
    # A worker whose heartbeat is far in the past is unhealthy; the policy replaces it.
    stale_ms = (settings.worker_unhealthy_after_seconds + 5) * 1000
    now_ms = await queue.now_ms()
    await redis_client.hset(
        "ql:workers",
        "worker-stale",
        f'{{"state":"idle","current_job":null,"last_heartbeat":{now_ms - stale_ms}}}',
    )

    decision = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )

    assert decision.action == "replace"
    assert decision.worker_id == "worker-stale"
    # Killed the stale one, dropped it from the registry, and stood a replacement up.
    assert docker_control.killed == ["worker-stale"]
    assert docker_control.started == 1
    assert await queue.list_workers() == {}
    # One audit row: kill-one-start-one leaves the count unchanged at one.
    (event,) = await _scaling_events(database)
    assert event.action == "replace"
    assert event.worker_id == "worker-stale"
    assert event.worker_count_after == 1


# ---- End-to-end: flood up to the cap, then idle down to the floor ---------------------


class RegisteringDockerControl(FakeDockerControl):
    """A fake whose started workers can be registered in ``ql:workers`` between ticks.

    A real spawned container boots and registers a moment later; this stands in for that lag in a
    deterministic way — the test calls :meth:`register_pending` after each tick so the next tick's
    worker count reflects the workers this fake "spawned". Kills are handled by the loop itself
    (it deregisters the worker it killed), so the fake only needs to track the start side here.
    """

    def __init__(self) -> None:
        super().__init__()
        self._registered = 0

    async def register_pending(self, queue) -> None:
        """Register one fresh worker per still-unregistered start since the last call."""
        while self._registered < self.started:
            self._registered += 1
            await queue.heartbeat(f"sim-worker-{self._registered}", state="idle", current_job=None)


async def test_autoscaler_scales_up_to_the_cap_then_idle_scales_down_to_the_floor(
    queue, redis_client, database, make_job
):
    # A small, fast configuration so the test is bounded and deterministic.
    test_settings = Settings(
        max_workers=3,
        min_workers=1,
        scale_up_threshold=5,
        scale_down_threshold=1,
        idle_timeout_seconds=1,
    )
    docker_control = RegisteringDockerControl()
    tracker = IdleTracker()

    # --- Flood: enqueue well past scale_up_threshold * max_workers ---
    for _ in range(test_settings.scale_up_threshold * test_settings.max_workers + 5):
        await queue.enqueue(make_job())

    # Drive ticks until the fleet stops growing — it must climb to the cap and hold there.
    for _ in range(5):
        await _run_one_tick(queue, docker_control, tracker, database, settings=test_settings)
        await docker_control.register_pending(queue)
    assert len(await queue.list_workers()) == test_settings.max_workers
    assert docker_control.started == test_settings.max_workers  # never overshot the cap

    # --- Drain the queue and let it sit idle past the timeout ---
    await redis_client.delete(READY_KEY)
    # Prime the idle streak to a point well in the past, so each drained tick reads "long idle"
    # without the test having to wait real seconds.
    long_ago_ms = await queue.now_ms() - 100_000
    tracker.update(0, now_ms=long_ago_ms, threshold=test_settings.scale_down_threshold)

    # Drive ticks until the fleet stops shrinking — it must fall to the floor and hold there.
    for _ in range(5):
        await _run_one_tick(queue, docker_control, tracker, database, settings=test_settings)
    assert len(await queue.list_workers()) == test_settings.min_workers
    # Trimmed exactly down from the cap to the floor, one worker per tick.
    assert len(docker_control.killed) == test_settings.max_workers - test_settings.min_workers

    # The audit trail captured every action: one scale_up plus the scale_downs, nothing for no-ops.
    actions = [event.action for event in await _scaling_events(database)]
    assert actions[0] == "scale_up"
    assert actions.count("scale_down") == test_settings.max_workers - test_settings.min_workers
    assert "no-op" not in actions
