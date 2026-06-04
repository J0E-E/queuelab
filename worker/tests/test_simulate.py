"""Unit tests for the simulated work profiles (Epic 8a).

Pure and deterministic — no Docker, no Redis, no real sleeps. Randomness is injected: a
small ``FixedRandom`` stub pins the jitter and pass/fail draw so each test asserts the
TDD §5.4 formula exactly, and a seeded ``random.Random`` checks the jitter stays in range.
"""

from __future__ import annotations

import random

import pytest

from simulate import (
    BASE_DURATION_MS,
    BASE_FAILURE_RATE,
    JITTER_RANGE,
    simulated_duration_ms,
    simulated_job_succeeds,
)

ALL_JOB_TYPES = ("email", "report", "image", "webhook")


class FixedRandom:
    """A drop-in for ``random.Random`` that returns preset values (deterministic tests).

    ``uniform`` always returns ``jitter_value`` (the duration jitter factor) and ``random``
    always returns ``draw_value`` (the pass/fail draw), so a test can place the draw exactly
    on either side of a failure threshold.
    """

    def __init__(self, *, jitter_value: float = 1.0, draw_value: float = 0.5) -> None:
        self.jitter_value = jitter_value
        self.draw_value = draw_value

    def uniform(self, low: float, high: float) -> float:
        return self.jitter_value

    def random(self) -> float:
        return self.draw_value


# --- Phase 1: duration profiles -------------------------------------------------------


def test_duration_scales_linearly_with_complexity():
    """With jitter pinned to 1.0, duration is exactly base * complexity."""
    no_jitter = FixedRandom(jitter_value=1.0)
    for complexity in range(1, 6):
        assert simulated_duration_ms("image", complexity, rng=no_jitter) == 1000 * complexity


def test_duration_applies_the_jitter_factor():
    """The jitter factor multiplies the scaled base and the result is rounded to an int."""
    low_jitter = FixedRandom(jitter_value=JITTER_RANGE[0])  # 0.85
    high_jitter = FixedRandom(jitter_value=JITTER_RANGE[1])  # 1.15
    assert simulated_duration_ms("report", 2, rng=low_jitter) == round(800 * 2 * 0.85)
    assert simulated_duration_ms("report", 2, rng=high_jitter) == round(800 * 2 * 1.15)


@pytest.mark.parametrize("job_type", ALL_JOB_TYPES)
def test_duration_stays_within_jitter_range_for_every_type(job_type: str):
    """Across many seeded draws the duration never escapes the ±15% jitter band."""
    seeded = random.Random(1234)
    base = BASE_DURATION_MS[job_type]
    for complexity in range(1, 6):
        lowest = round(base * complexity * JITTER_RANGE[0])
        highest = round(base * complexity * JITTER_RANGE[1])
        for _ in range(200):
            duration_ms = simulated_duration_ms(job_type, complexity, rng=seeded)
            assert lowest <= duration_ms <= highest


def test_duration_defined_for_all_four_job_types():
    """A duration profile exists for every known job type (TDD verification)."""
    assert set(BASE_DURATION_MS) == set(ALL_JOB_TYPES)


def test_duration_rejects_an_unknown_type():
    """An unknown type is a programming error, surfaced as a clear ValueError."""
    with pytest.raises(ValueError, match="unknown job type"):
        simulated_duration_ms("teleport", 1, rng=FixedRandom())


# --- Phase 2: failure outcome ---------------------------------------------------------


def test_outcome_passes_when_the_draw_is_at_or_above_the_threshold():
    """image@c5 fails with probability 0.25; a draw of 0.26 sits just above → it passes."""
    just_above = FixedRandom(draw_value=0.26)
    assert simulated_job_succeeds("image", 5, rng=just_above) is True


def test_outcome_fails_when_the_draw_is_below_the_threshold():
    """A draw of 0.24 sits just below image@c5's 0.25 threshold → it fails."""
    just_below = FixedRandom(draw_value=0.24)
    assert simulated_job_succeeds("image", 5, rng=just_below) is False


def test_higher_complexity_raises_the_failure_rate():
    """Same draw between the two thresholds: low complexity passes, high complexity fails."""
    # email fail probability: 0.02 at c1, 0.10 at c5. A 0.05 draw lands between them.
    between = FixedRandom(draw_value=0.05)
    assert simulated_job_succeeds("email", 1, rng=between) is True
    assert simulated_job_succeeds("email", 5, rng=between) is False


def test_failure_bias_raises_the_failure_rate():
    """A job that passes at bias 0 can be pushed to fail by a positive chaos bias."""
    draw = FixedRandom(draw_value=0.30)
    # image@c5 base threshold is 0.25, so a 0.30 draw passes without bias...
    assert simulated_job_succeeds("image", 5, rng=draw) is True
    # ...but a +0.5 bias lifts the threshold to 0.75, so the same draw now fails.
    assert simulated_job_succeeds("image", 5, rng=draw, failure_bias=0.5) is False


def test_failure_bias_default_matches_no_bias():
    """The default failure_bias=0.0 is a true no-op."""
    draw = FixedRandom(draw_value=0.5)
    assert simulated_job_succeeds("report", 3, rng=draw) == simulated_job_succeeds(
        "report", 3, rng=draw, failure_bias=0.0
    )


def test_large_positive_bias_clamps_to_always_fail():
    """A bias that pushes the probability past 1.0 is clamped — the job always fails."""
    almost_one = FixedRandom(draw_value=0.999)
    assert simulated_job_succeeds("email", 1, rng=almost_one, failure_bias=1.0) is False


def test_negative_bias_clamps_to_never_fail():
    """A bias below the base rate is clamped at 0.0 — the job always passes."""
    lowest_draw = FixedRandom(draw_value=0.0)
    assert simulated_job_succeeds("image", 5, rng=lowest_draw, failure_bias=-5.0) is True


def test_outcome_defined_for_all_four_job_types():
    """A failure profile exists for every known job type (TDD verification)."""
    assert set(BASE_FAILURE_RATE) == set(ALL_JOB_TYPES)


def test_outcome_rejects_an_unknown_type():
    """An unknown type raises the same clear ValueError as the duration function."""
    with pytest.raises(ValueError, match="unknown job type"):
        simulated_job_succeeds("teleport", 1, rng=FixedRandom())
