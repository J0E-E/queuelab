"""In-context architecture notes served to the dashboard (Epic 15).

A small, static body of terminal-voiced copy that explains the mechanics the live panes show — the
custom Redis queue, the autoscaler, chaos recovery, the real-time layer, and the guardrails. It
lives server-side (not baked into the frontend bundle) so the copy can change without a rebuild,
and each section's ``key`` lets the UI anchor a note beside the pane it explains.
``GET /api/architecture`` returns these; the explainer pages (Epic 16) can reuse the same source.
"""

from __future__ import annotations

# Each section explains one mechanic, keyed to the dashboard pane that shows it.
ARCHITECTURE_SECTIONS: list[dict[str, str]] = [
    {
        "key": "queue",
        "title": "Custom Redis queue",
        "body": (
            "Jobs are not handed to a library broker — they live in raw Redis primitives. A ready "
            "list, a delayed sorted-set, a per-worker processing list, and a leases set together "
            "give real claiming, time-limited leases, retries with backoff, and recovery. Every "
            "deadline is stamped from Redis TIME inside atomic Lua, so one clock rules all workers."
        ),
    },
    {
        "key": "workers",
        "title": "Autoscaler",
        "body": (
            "A separate control loop reads the queue depth and the worker registry every couple "
            "of seconds and decides one action: grow the fleet under load, trim an idle worker "
            "after a quiet stretch, or replace one whose heartbeat went stale. Scaling is visible "
            "here as cells appearing and disappearing in the grid."
        ),
    },
    {
        "key": "chaos",
        "title": "Break it on purpose",
        "body": (
            "Destroy a worker and its in-flight job's lease lapses; the reaper requeues the job "
            "and the autoscaler stands up a replacement — recovery you can watch. Inject failures "
            "biases the simulated outcomes toward failure for a while, then it expires back to "
            "normal on its own."
        ),
    },
    {
        "key": "realtime",
        "title": "Live multiplayer view",
        "body": (
            "One WebSocket carries a snapshot on connect, then per-job deltas, throttled metric "
            "ticks, and a readable activity line per event. Everyone watching the shared instance "
            "sees the same queue move at once — this dashboard is just a reducer over that stream."
        ),
    },
    {
        "key": "guardrails",
        "title": "Guardrails",
        "body": (
            "A shared instance needs limits: per-session token-bucket rate limits, batch and "
            "capacity caps, and validation that rejects in the system voice (a [ERR] line, a 429 "
            "with Retry-After, a 409 at capacity) rather than degrading for everyone."
        ),
    },
]


def get_architecture_sections() -> list[dict[str, str]]:
    """Return the architecture notes as ``[{key, title, body}]`` for ``GET /api/architecture``."""
    return ARCHITECTURE_SECTIONS
