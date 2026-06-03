"""Ephemeral guest identity: a per-session handle and color (TDD §2, §5.8).

A visitor never logs in. The first time their browser asks for a session we hand back a
throwaway identity used only to attribute their actions in the activity feed: a random
id, a handle like ``guest-teal``, and the matching color.

The scheme is deliberately simple — a handle is literally ``guest-<colorname>`` and the
color is that name's hex value. The names come from a fixed, phosphor-safe set in the UI
style guide (§3.4), kept distinct from the job-state hues so a handle never looks like a
status. There are only a handful of colors, so two visitors can share one; that is fine
because the identity is for display attribution only, not security.

This module does no input/output (no Redis, no database) — it is a pure function, which
keeps it trivially testable and reusable by later epics (e.g. job submission attribution).
"""

from __future__ import annotations

import random
from uuid import uuid4

from pydantic import BaseModel

# The fixed guest-handle color set from UI style guide §3.4 — name → hex. These are picked
# to stay legible on the near-black background and to not collide with the job-state colors.
GUEST_COLORS: dict[str, str] = {
    "teal": "#2dd4bf",
    "pink": "#ff5fd2",
    "lime": "#aaff00",
    "sky": "#5ab0ff",
    "orange": "#ff8c42",
    "lavender": "#c77dff",
}


class GuestIdentity(BaseModel):
    """The throwaway identity handed to a visitor for one session (TDD §5.8).

    ``session_id`` tracks the visitor across later requests (rate limits, job attribution);
    ``guest_handle`` is the display name (``guest-<colorname>``); ``color`` is the hex the
    UI renders that handle in.
    """

    session_id: str
    guest_handle: str
    color: str


def create_guest_identity() -> GuestIdentity:
    """Build a fresh guest identity with a random color from the fixed set (§3.4).

    Picks one color name at random, names the handle after it (``guest-<colorname>``), and
    stamps a unique session id. Collisions on color are possible and acceptable — the
    identity is for feed attribution, not authentication.
    """
    color_name = random.choice(list(GUEST_COLORS))
    return GuestIdentity(
        session_id=uuid4().hex,
        guest_handle=f"guest-{color_name}",
        color=GUEST_COLORS[color_name],
    )
