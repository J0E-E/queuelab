"""The autoscaler process: a long-lived control loop that scales workers by queue depth (Epic 11c).

Epics 11a and 11b built the autoscaler's brain (:func:`app.services.autoscaler.decide_scaling`, a
pure policy) and its hands (:class:`app.services.docker_control.DockerControl`, a Docker wrapper).
This module is the process that ties them together: every ``autoscaler_loop_seconds`` it reads the
queue depth and the worker registry, tracks how long the queue has sat quiet, asks the policy for
one action, and carries it out through Docker.

The loop is intentionally one-action-per-tick — the policy returns at most a single
:class:`ScalingDecision`, so a runaway flood grows the fleet a few workers per tick (a ``scale_up``
may add several at once) and a drained queue trims one idle worker per tick down to ``min_workers``.

It runs until SIGTERM (``docker compose stop``) or SIGINT (Ctrl-C in local dev), mirroring the
worker's graceful-shutdown shape so the process stops cleanly between ticks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
from dataclasses import replace
from datetime import UTC, datetime

from pydantic import ValidationError

from app.config import OVERRIDABLE_CONFIG_KEYS, Settings, settings
from app.db.engine import Database
from app.models.scaling_event import ScalingEvent
from app.queue.client import JobQueue
from app.queue.protocol import CONTROL_CHANNEL
from app.realtime.subscriber import run_state_subscriber
from app.services.autoscaler import ScalingDecision, decide_scaling
from app.services.docker_control import DockerControl

logger = logging.getLogger(__name__)


class IdleTracker:
    """Tracks how long the queue has sat at or below the scale-down threshold.

    The worker registry can't reveal idle duration on its own — a worker's heartbeat refreshes
    every few seconds whether it is busy or not — so the control loop measures it here and hands
    the result to the policy. The first tick that finds the queue quiet stamps the start time; the
    first tick that finds it busy again clears it, so the count is the *continuous* quiet stretch.
    """

    def __init__(self) -> None:
        self._idle_since_ms: int | None = None

    def update(self, queue_depth: int, *, now_ms: int, threshold: int) -> int:
        """Fold in this tick's reading and return how many whole seconds the queue has been quiet.

        Returns ``0`` whenever the queue is above ``threshold`` (busy), and resets the streak so a
        brief lull doesn't carry over into the next quiet stretch.
        """
        if queue_depth > threshold:
            self._idle_since_ms = None
            return 0
        if self._idle_since_ms is None:
            self._idle_since_ms = now_ms
        return (now_ms - self._idle_since_ms) // 1000


async def run_autoscaler(
    queue: JobQueue,
    docker_control: DockerControl,
    database: Database,
    *,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Run the control loop until ``stop_event`` is set, one decision per tick.

    Each tick is best-effort: a failure (a Redis blip, a Docker hiccup) is logged and the loop
    carries on to the next tick, so one bad tick never tears the process down. Between ticks it
    sleeps up to ``autoscaler_loop_seconds`` but wakes immediately when asked to stop.
    """
    idle_tracker = IdleTracker()
    while not stop_event.is_set():
        try:
            await _run_one_tick(queue, docker_control, idle_tracker, database, settings=settings)
        except Exception:
            logger.exception("autoscaler tick failed; will retry next tick")
        await _sleep_until_stop(stop_event, seconds=settings.autoscaler_loop_seconds)


async def run_control_consumer(
    queue: JobQueue,
    docker_control: DockerControl,
    database: Database,
    *,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Consume manual scaling commands off ``ql:control`` and carry each one out (Epic 11d-1).

    Runs beside the tick loop in the same process so a manual command lands through the exact same
    Docker control and audit trail as an automatic one. The subscribe loop, its re-subscribe guard,
    and "one bad message never unwinds the loop" all come from the shared
    :func:`run_state_subscriber`; this only supplies the per-command handler. The handler is
    best-effort — a malformed or unknown command is logged and skipped, never crashing the consumer.
    The subscriber runs until cancelled; this waits on ``stop_event`` and cancels it so the consumer
    winds down with the rest of the process on SIGTERM/SIGINT.
    """

    async def handle_message(message: dict) -> None:
        await _handle_control_command(message, queue, docker_control, database, settings=settings)

    subscriber = asyncio.create_task(
        run_state_subscriber(queue, CONTROL_CHANNEL, handle_message, name="control")
    )
    try:
        await stop_event.wait()
    finally:
        subscriber.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await subscriber


async def _handle_control_command(
    message: dict,
    queue: JobQueue,
    docker_control: DockerControl,
    database: Database,
    *,
    settings: Settings,
) -> None:
    """Map one published command to a :class:`ScalingDecision` and run it through the shared tail.

    Best-effort: a malformed payload (bad JSON, missing ``count``, unknown verb) is logged and
    skipped so the shared subscribe loop stays alive across it. A recognized command becomes a
    decision with a ``manual:`` reason and goes through :func:`_apply_decision`, so it is clamped,
    carried out, and audited exactly like a tick's decision — the worker count for the audit row is
    read live from the registry, the same source the tick uses.
    """
    try:
        decision = _command_to_decision(json.loads(message["data"]))
        if decision is None:
            return
        settings = await _effective_settings(queue, settings)
        worker_count_before = len(await queue.list_workers())
        await _apply_decision(
            decision,
            queue,
            docker_control,
            database,
            worker_count_before=worker_count_before,
            settings=settings,
        )
    except Exception:
        logger.exception("control consumer: failed to handle a command; skipping")


def _command_to_decision(command: dict) -> ScalingDecision | None:
    """Translate a manual command dict into a :class:`ScalingDecision`, or ``None`` to skip it.

    The contract (Epic 11d-1, also published by Epic 12 / Epic 14) is
    ``{"command": "scale_up", "count": N}`` / ``{"command": "scale_down", "worker_id": "X"}``. The
    ``command`` verbs match the ``ScalingDecision.action`` vocabulary so they map straight across.
    Anything else — an unknown verb, a ``scale_up`` without a positive ``count``, a ``scale_down``
    without a ``worker_id`` — is logged and skipped (returns ``None``), never executed.
    """
    verb = command.get("command")
    if verb == "scale_up":
        count = command.get("count")
        # bool is an int subclass, so reject it explicitly — a JSON ``true`` is not a count.
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            logger.warning(
                "control consumer: scale_up missing a positive count; skipping: %s", command
            )
            return None
        return ScalingDecision(action="scale_up", count=count, reason=f"manual: scale_up {count}")
    if verb == "scale_down":
        worker_id = command.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id:
            logger.warning(
                "control consumer: scale_down missing a worker_id; skipping: %s", command
            )
            return None
        return ScalingDecision(
            action="scale_down", worker_id=worker_id, reason=f"manual: scale_down {worker_id}"
        )
    logger.warning("control consumer: unknown command; skipping: %s", command)
    return None


async def _effective_settings(queue: JobQueue, base_settings: Settings) -> Settings:
    """Merge the live ``ql:config`` overrides over the env-loaded base and return the result.

    An operator can retune the autoscaler thresholds at runtime (Epic 11d-2) via
    ``PUT /api/config``, which writes a sparse patch into ``ql:config``. The control loop reads that
    patch each tick (and each manual command) and folds it over the base settings here, so a change
    takes effect within a tick without a redeploy. Only :data:`OVERRIDABLE_CONFIG_KEYS` are honored;
    any other stored key is ignored. The merged values are revalidated through the ``Settings``
    model, so a stored override that breaks a cross-field bound (e.g. ``scale_down_threshold`` above
    ``scale_up_threshold``) is logged and the base settings are used unchanged — a bad override
    never crashes or stalls the loop.
    """
    overrides = await queue.get_config()
    safe = {key: value for key, value in overrides.items() if key in OVERRIDABLE_CONFIG_KEYS}
    if not safe:
        return base_settings
    try:
        return Settings(**{**base_settings.model_dump(), **safe})
    except ValidationError:
        logger.warning("ignoring invalid ql:config override %s; using base settings", safe)
        return base_settings


async def _run_one_tick(
    queue: JobQueue,
    docker_control: DockerControl,
    idle_tracker: IdleTracker,
    database: Database,
    *,
    settings: Settings,
) -> ScalingDecision:
    """Read the live snapshot, decide one action, carry it out, record it, and return it.

    Factored out of the loop so a test can drive a single tick deterministically. The worker count
    comes from the registry (``ql:workers``) the policy already reasons over, not from Docker, so a
    worker counts only once it has actually booted and registered. Every action but ``no-op`` is
    written to Postgres as an audit row.
    """
    settings = await _effective_settings(queue, settings)
    queue_depth = await queue.queue_depth()
    workers = await queue.list_workers()
    now_ms = await queue.now_ms()
    queue_idle_seconds = idle_tracker.update(
        queue_depth, now_ms=now_ms, threshold=settings.scale_down_threshold
    )
    decision = decide_scaling(
        queue_depth=queue_depth,
        workers=workers,
        queue_idle_seconds=queue_idle_seconds,
        settings=settings,
        now_ms=now_ms,
    )
    return await _apply_decision(
        decision,
        queue,
        docker_control,
        database,
        worker_count_before=len(workers),
        settings=settings,
    )


async def _apply_decision(
    decision: ScalingDecision,
    queue: JobQueue,
    docker_control: DockerControl,
    database: Database,
    *,
    worker_count_before: int,
    settings: Settings,
) -> ScalingDecision:
    """Clamp, carry out, and record one decision — the shared tail of automatic and manual actions.

    Both the tick (:func:`_run_one_tick`) and a manual command (:func:`run_control_consumer`) feed
    their decision through here, so the two paths can't drift: a manual ``scale_up`` is clamped to
    the running cap exactly as the policy's is, and every executed action — automatic or manual —
    writes the same ``scaling_event`` audit row and publishes the same activity-feed line. A
    ``no-op`` (including a ``scale_up`` the clamp suppressed at the cap) records nothing. Returns
    the decision as actually executed (post-clamp), so a caller can see what ran.
    """
    decision = _clamp_scale_up_to_running_cap(decision, docker_control, settings=settings)
    worker_count_after = _worker_count_after(decision, worker_count_before=worker_count_before)
    await _carry_out_decision(decision, queue, docker_control)
    if decision.action != "no-op":
        event = {
            "action": decision.action,
            "worker_id": decision.worker_id,
            "reason": decision.reason,
            "worker_count_after": worker_count_after,
        }
        # Record the durable audit row first (best-effort: a DB failure is logged with the full
        # event, not raised, so the action it executed is never silently lost), then publish the
        # same payload to the live feed regardless.
        await _record_scaling_event(database, event)
        await queue.publish_scaling_event(event)
    return decision


def _clamp_scale_up_to_running_cap(
    decision: ScalingDecision, docker_control: DockerControl, *, settings: Settings
) -> ScalingDecision:
    """Clamp a ``scale_up`` against the *running* container count so the hard cap can't be overshot.

    :func:`decide_scaling` caps the fleet against the worker registry, but a freshly spawned
    container takes a few seconds to boot and register — longer than one tick — so several ticks of
    a sustained flood would each read the same stale registry count and re-spawn, pushing the
    running fleet past ``max_workers``. Counting the containers Docker is actually running (a
    spawned container is "running" the moment it starts, well before it registers) closes that
    window, and likewise stops a just-replaced worker's not-yet-registered replacement from
    triggering a spurious extra spawn. Non-``scale_up`` decisions pass through untouched.
    """
    if decision.action != "scale_up":
        return decision
    running = len(docker_control.list_workers())
    allowed = max(0, settings.max_workers - running)
    if allowed >= decision.count:
        return decision
    if allowed == 0:
        return ScalingDecision(
            action="no-op",
            reason=f"scale_up suppressed: {running} workers already running at cap "
            f"{settings.max_workers}",
        )
    return replace(decision, count=allowed)


async def _carry_out_decision(
    decision: ScalingDecision, queue: JobQueue, docker_control: DockerControl
) -> None:
    """Turn one decision into Docker calls, logging each action; ``no-op`` does nothing.

    A killed worker is also dropped from the registry: a force-removed container can't run its own
    graceful deregister, so without this its stale field would linger and re-trigger ``replace``
    forever. ``replace`` spawns a fresh worker in the same tick — kill the unhealthy one, stand a
    new one up.
    """
    if decision.action == "scale_up":
        for _ in range(decision.count):
            docker_control.start_worker()
        logger.info("autoscaler: scaled up +%d — %s", decision.count, decision.reason)
    elif decision.action == "scale_down":
        docker_control.kill_worker(decision.worker_id)
        await queue.deregister_worker(decision.worker_id)
        logger.info("autoscaler: scaled down %s — %s", decision.worker_id, decision.reason)
    elif decision.action == "replace":
        docker_control.kill_worker(decision.worker_id)
        await queue.deregister_worker(decision.worker_id)
        docker_control.start_worker()
        logger.info("autoscaler: replaced %s — %s", decision.worker_id, decision.reason)


def _worker_count_after(decision: ScalingDecision, *, worker_count_before: int) -> int:
    """The intended worker count once this decision lands.

    Computed arithmetically rather than re-read from the registry, because a freshly spawned
    container takes a moment to boot and register, so an immediate re-read would still show the old
    count. ``replace`` swaps one for one, leaving the count unchanged.
    """
    if decision.action == "scale_up":
        return worker_count_before + decision.count
    if decision.action == "scale_down":
        return worker_count_before - 1
    return worker_count_before


async def _record_scaling_event(database: Database, event: dict) -> None:
    """Write one autoscaler action to the durable ``scaling_event`` audit trail.

    Takes the same event payload that is published to the feed, stamping the row's ``at`` from the
    wall clock — the row is an audit timestamp for ordering and retention, not a queue deadline.

    The Docker action has *already* happened by the time we record it, so a DB failure must not bury
    the executed step: the write is best-effort and logs the full event on failure (rather than
    raising) so the action survives in the logs and the live-feed publish still goes out.
    """
    try:
        async with database.session() as session:
            session.add(
                ScalingEvent(
                    at=datetime.now(UTC),
                    action=event["action"],
                    worker_id=event["worker_id"],
                    reason=event["reason"],
                    worker_count_after=event["worker_count_after"],
                )
            )
            await session.commit()
    except Exception:
        logger.exception("autoscaler: failed to record scaling_event; action executed: %s", event)


async def _sleep_until_stop(stop_event: asyncio.Event, *, seconds: float) -> None:
    """Sleep up to ``seconds``, returning early the moment ``stop_event`` is set."""
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)


async def main() -> None:
    """Build the clients, run the control loop until stopped, then close everything cleanly."""
    queue = JobQueue.from_settings()
    docker_control = DockerControl.from_settings()
    database = Database.from_settings()
    stop_event = asyncio.Event()

    # Docker stop sends SIGTERM; Ctrl-C in local dev sends SIGINT. Both ask the loop to wind down
    # between ticks. add_signal_handler isn't implemented on Windows (dev-only — the autoscaler
    # runs in a Linux container), so suppress that and fall back to no handler there.
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signal_number, stop_event.set)

    try:
        # The tick loop and the manual-control consumer run side by side on one stop_event: a
        # SIGTERM/SIGINT sets it and both wind down together (Epic 11d-1). gather propagates the
        # first failure, so a fatal error in either tears the process down rather than leaving a
        # half-running autoscaler.
        await asyncio.gather(
            run_autoscaler(
                queue, docker_control, database, settings=settings, stop_event=stop_event
            ),
            run_control_consumer(
                queue, docker_control, database, settings=settings, stop_event=stop_event
            ),
        )
    finally:
        docker_control.close()
        await queue.aclose()
        await database.aclose()


if __name__ == "__main__":
    asyncio.run(main())
