"""Unit tests for the ephemeral guest identity service (Epic 5).

These are pure (no Redis/Postgres) — they only check the handle/color/id assignment rules.
"""

from __future__ import annotations

from app.services.identity import GUEST_COLORS, create_guest_identity


def test_handle_names_a_color_from_the_fixed_set():
    """The handle is always ``guest-<colorname>`` for a name in the §3.4 set."""
    identity = create_guest_identity()
    assert identity.guest_handle.startswith("guest-")
    color_name = identity.guest_handle.removeprefix("guest-")
    assert color_name in GUEST_COLORS


def test_color_matches_its_handle_name():
    """The returned color is exactly the hex the handle's color name maps to."""
    identity = create_guest_identity()
    color_name = identity.guest_handle.removeprefix("guest-")
    assert identity.color == GUEST_COLORS[color_name]


def test_session_id_is_non_empty():
    """Every identity carries a non-empty session id."""
    identity = create_guest_identity()
    assert identity.session_id


def test_session_ids_are_unique_across_calls():
    """Two sessions never share a session id, even if they share a color."""
    session_ids = {create_guest_identity().session_id for _ in range(100)}
    assert len(session_ids) == 100


def test_every_color_is_eventually_assignable():
    """Across many draws the picker can reach every color in the set (no name is stranded)."""
    seen_colors = {create_guest_identity().guest_handle for _ in range(500)}
    expected = {f"guest-{name}" for name in GUEST_COLORS}
    assert seen_colors == expected
