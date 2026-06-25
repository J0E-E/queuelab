"""Tests for the autoscaler control loop (Epic 11c): the tick, idle tracking, and execution.

The policy (Epic 11a) and the Docker wrapper (Epic 11b) are already tested in isolation; these
tests cover the loop that ties them together. ``IdleTracker`` is pure, so it is unit-tested with
plain integers. The tick runs against a real Redis (testcontainers) seeded through
``queue.heartbeat`` so the registry the policy reads is genuine, with a **fake DockerControl** that
records start/kill calls instead of touching a daemon — no Docker required.
"""

from __future__ import annotations

import asyncio
import contextlib

from app.autoscaler_main import (
    SYSTEM_ACTOR_COLOR,
    SYSTEM_ACTOR_HANDLE,
    IdleTracker,
    _handle_control_command,
    _run_one_tick,
    run_control_consumer,
)
from app.config import Settings, settings
from app.models.scaling_event import ScalingEvent
from app.queue.protocol import CONTROL_CHANNEL, READY_KEY
from sqlalchemy import select


class FakeDockerControl:
    """A stand-in DockerControl that records what the loop asked it to do, no daemon needed."""

    def __init__(self) -> None:
        self.started = 0
        self.killed: list[str] = []
        # Worker ids whose container is already gone, so a kill is a no-op (returns False) — the
        # real ``kill_worker`` returns False on a Docker ``NotFound``. Empty by default.
        self.already_gone: set[str] = set()

    def start_worker(self) -> None:
        self.started += 1

    def kill_worker(self, worker_id: str) -> bool:
        self.killed.append(worker_id)
        return worker_id not in self.already_gone

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


async def test_tick_honors_a_live_config_override(queue, redis_client, database, make_job):
    docker_control = FakeDockerControl()
    # One worker at the floor and a queue depth below the env scale-up threshold — base settings
    # would leave it alone.
    await _seed_worker(queue, "worker-1")
    for _ in range(settings.scale_up_threshold - 2):
        await queue.enqueue(make_job())

    baseline = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )
    assert baseline.action == "no-op"

    # Lower the threshold live via ql:config; the very next tick now sees the same depth as hot and
    # scales up — the override took effect without changing the env-loaded settings.
    await queue.set_config({"scale_up_threshold": 1})
    overridden = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )
    assert overridden.action == "scale_up"
    assert docker_control.started == overridden.count


async def test_tick_ignores_an_invalid_config_override(queue, redis_client, database, make_job):
    docker_control = FakeDockerControl()
    await _seed_worker(queue, "worker-1")
    for _ in range(settings.scale_up_threshold - 2):
        await queue.enqueue(make_job())

    # A patch that is internally inconsistent once merged (scale_down above scale_up) fails the
    # Settings validators, so the merge discards it and the tick runs on the env baseline — the
    # would-be-effective scale_up_threshold=1 is never applied, so the tick stays a no-op.
    await queue.set_config({"scale_up_threshold": 1, "scale_down_threshold": 99})
    decision = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )

    assert decision.action == "no-op"
    assert docker_control.started == 0


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


# ---- The manual control consumer (Epic 11d-1): commands off ql:control -----------------


async def _poll_until(check, *, attempts: int = 200, interval: float = 0.02):
    """Poll ``check`` until it returns a truthy result, then return it; fail if it never does."""
    for _ in range(attempts):
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met within the poll window")


@contextlib.asynccontextmanager
async def _running_control_consumer(queue, docker_control, database, *, run_settings):
    """Run the control consumer as a background task for the block, then stop it via stop_event."""
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_control_consumer(
            queue, docker_control, database, settings=run_settings, stop_event=stop_event
        )
    )
    try:
        # Pub/sub has no replay, so wait until the subscription is live before publishing.
        async def _subscribed():
            counts = await queue._redis.pubsub_numsub(CONTROL_CHANNEL)
            return bool(counts) and counts[0][1] >= 1

        await _poll_until(_subscribed)
        yield task
    finally:
        stop_event.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_control_scale_up_spawns_containers_and_audits(queue, redis_client, database):
    docker_control = FakeDockerControl()

    async with _running_control_consumer(queue, docker_control, database, run_settings=settings):
        await queue.publish_control_command({"command": "scale_up", "count": 2})
        await _poll_until(lambda: _settled(docker_control.started == 2))

    assert docker_control.killed == []
    # One audit row + one published feed line, with a manual reason and the count that ran.
    (event,) = await _scaling_events(database)
    assert event.action == "scale_up"
    assert event.reason == "manual: scale_up 2"
    assert event.worker_count_after == 2


async def test_control_scale_down_kills_deregisters_and_audits(queue, redis_client, database):
    docker_control = FakeDockerControl()
    await _seed_worker(queue, "worker-1")
    await _seed_worker(queue, "worker-2")

    async with _running_control_consumer(queue, docker_control, database, run_settings=settings):
        await queue.publish_control_command({"command": "scale_down", "worker_id": "worker-1"})
        await _poll_until(lambda: _settled(docker_control.killed == ["worker-1"]))

    # The named worker is killed and gone from the registry; the survivor remains.
    assert docker_control.started == 0
    assert set((await queue.list_workers()).keys()) == {"worker-2"}
    (event,) = await _scaling_events(database)
    assert event.action == "scale_down"
    assert event.worker_id == "worker-1"
    assert event.reason == "manual: scale_down worker-1"
    assert event.worker_count_after == 1


async def _settled(condition: bool) -> bool:
    """Adapter so a plain boolean can drive the async ``_poll_until`` checker."""
    return condition


# ---- Edge cases: clamp, malformed/unknown, gone worker (handler driven directly) -------


async def test_control_destroy_kills_without_deregister(queue, redis_client, database):
    docker_control = FakeDockerControl()
    await _seed_worker(queue, "worker-1")
    await _seed_worker(queue, "worker-2")

    await _handle_control_command(
        {"data": '{"command":"destroy","worker_id":"worker-1"}'},
        queue,
        docker_control,
        database,
        settings=settings,
    )

    # The container is hard-killed, but its registry entry is left stale on purpose: that is what
    # lets the reaper recover its in-flight job and the next tick's replace stand a fresh worker up.
    assert docker_control.killed == ["worker-1"]
    assert docker_control.started == 0
    assert set((await queue.list_workers()).keys()) == {"worker-1", "worker-2"}
    (event,) = await _scaling_events(database)
    assert event.action == "destroy"
    assert event.worker_id == "worker-1"
    assert event.reason == "chaos: destroy worker-1"
    assert event.worker_count_after == 1  # two workers minus the destroyed one


async def test_control_destroy_of_an_already_gone_worker_records_nothing(
    queue, redis_client, database, monkeypatch
):
    # Because destroy leaves the worker registered (so the reaper can recover it), an
    # already-destroyed worker stays a valid target until the reaper clears it — a repeat or random
    # destroy then hits a container that is already gone. That kill is a no-op, so no "destroyed"
    # audit row or feed line is written (no phantom success).
    docker_control = FakeDockerControl()
    await _seed_worker(queue, "worker-1")
    docker_control.already_gone = {"worker-1"}
    published: list[dict] = []

    async def _capture(event):
        published.append(event)

    monkeypatch.setattr(queue, "publish_scaling_event", _capture)

    await _handle_control_command(
        {"data": '{"command":"destroy","worker_id":"worker-1"}'},
        queue,
        docker_control,
        database,
        settings=settings,
    )

    # It still attempted the kill, but nothing was recorded or published — the line stays honest.
    assert docker_control.killed == ["worker-1"]
    assert await _scaling_events(database) == []
    assert published == []


async def test_control_destroy_attributes_the_triggering_guest(
    queue, redis_client, database, monkeypatch
):
    # A destroy command carries the triggering guest (the chaos endpoint stamped it on); the
    # published scaling line is attributed to that guest's handle + color (Epic 17b). We capture the
    # published event rather than subscribe, keeping the test deterministic with no live socket.
    docker_control = FakeDockerControl()
    await _seed_worker(queue, "worker-1")
    published: list[dict] = []

    async def _capture(event):
        published.append(event)

    monkeypatch.setattr(queue, "publish_scaling_event", _capture)

    await _handle_control_command(
        {
            "data": '{"command":"destroy","worker_id":"worker-1",'
            '"handle":"guest-teal","color":"#2dd4bf"}'
        },
        queue,
        docker_control,
        database,
        settings=settings,
    )

    (event,) = published
    assert event["action"] == "destroy"
    assert event["handle"] == "guest-teal"
    assert event["color"] == "#2dd4bf"


async def test_automatic_scale_is_attributed_to_the_system_actor(
    queue, redis_client, database, make_job, monkeypatch
):
    # An automatic policy decision has no guest behind it, so its line is attributed to the reserved
    # system actor — handle "autoscaler" in the §3.3 info color, outside the guest palette.
    docker_control = FakeDockerControl()
    for _ in range(settings.scale_up_threshold * 2):
        await queue.enqueue(make_job())
    published: list[dict] = []

    async def _capture(event):
        published.append(event)

    monkeypatch.setattr(queue, "publish_scaling_event", _capture)

    decision = await _run_one_tick(
        queue, docker_control, IdleTracker(), database, settings=settings
    )

    assert decision.action == "scale_up"
    (event,) = published
    assert event["handle"] == SYSTEM_ACTOR_HANDLE == "autoscaler"
    assert event["color"] == SYSTEM_ACTOR_COLOR == "#36c5ff"


async def test_control_scale_up_over_cap_is_clamped_to_max_workers(queue, redis_client, database):
    docker_control = FakeDockerControl()
    over_cap = settings.max_workers + 5

    # Drive the handler directly with a fabricated pub/sub frame — deterministic, no live socket.
    await _handle_control_command(
        {"data": f'{{"command":"scale_up","count":{over_cap}}}'},
        queue,
        docker_control,
        database,
        settings=settings,
    )

    # The shared clamp held the hard cap: it spawned exactly max_workers, not the over-cap request.
    assert docker_control.started == settings.max_workers
    (event,) = await _scaling_events(database)
    assert event.action == "scale_up"
    # The audit records the count that actually ran (the clamped fleet size), not the request.
    assert event.worker_count_after == settings.max_workers


async def test_control_scale_down_of_a_gone_worker_is_harmless(queue, redis_client, database):
    docker_control = FakeDockerControl()
    # No such worker in the registry; kill_worker swallows NotFound and deregister is a no-op.
    await _handle_control_command(
        {"data": '{"command":"scale_down","worker_id":"ghost"}'},
        queue,
        docker_control,
        database,
        settings=settings,
    )

    # It still records the scale_down (the command did request an action); nothing crashed.
    assert docker_control.killed == ["ghost"]
    (event,) = await _scaling_events(database)
    assert event.action == "scale_down"
    assert event.worker_id == "ghost"


async def test_control_malformed_and_unknown_commands_are_skipped(queue, redis_client, database):
    docker_control = FakeDockerControl()
    bad_messages = [
        {"data": "not-json{"},  # unparseable JSON
        {"data": '{"command":"scale_up"}'},  # missing count
        {"data": '{"command":"scale_up","count":0}'},  # non-positive count
        {"data": '{"command":"scale_down"}'},  # missing worker_id
        {"data": '{"command":"obliterate"}'},  # unknown verb
        {"data": "{}"},  # no command key at all
    ]

    for message in bad_messages:
        # None of these crash the consumer; each is logged and skipped.
        await _handle_control_command(message, queue, docker_control, database, settings=settings)

    # Nothing was carried out and nothing was audited.
    assert docker_control.started == 0
    assert docker_control.killed == []
    assert await _scaling_events(database) == []
