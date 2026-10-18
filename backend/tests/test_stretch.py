"""Stretch's adaptive difficulty (issue #13): interpolation (anchors exact,
midpoints, always sums to 100), the after-session rule's thresholds
(including boundaries), clamping, and `describe_mix`'s own text -- no
database, same spirit as `test_stats_math.py`."""

from __future__ import annotations

import pytest

from app import stretch


# --- interpolation ------------------------------------------------------


def test_anchor_0_matches_easy_exactly() -> None:
    mix = stretch.interpolate(0)
    assert mix.unknown_kanji_target == pytest.approx(0.02)
    assert mix.jlpt_mix == {"n5": 0.70, "n4": 0.30, "n3": 0.0, "n2": 0.0, "n1": 0.0}


def test_anchor_1_matches_the_pre_13_static_stretch_exactly() -> None:
    mix = stretch.interpolate(1)
    assert mix.unknown_kanji_target == pytest.approx(0.05)
    assert mix.jlpt_mix == {"n5": 0.50, "n4": 0.35, "n3": 0.15, "n2": 0.0, "n1": 0.0}


def test_anchor_2_matches_challenge_exactly() -> None:
    mix = stretch.interpolate(2)
    assert mix.unknown_kanji_target == pytest.approx(0.10)
    assert mix.jlpt_mix == {"n5": 0.30, "n4": 0.35, "n3": 0.25, "n2": 0.10, "n1": 0.0}


def test_anchor_3() -> None:
    mix = stretch.interpolate(3)
    assert mix.unknown_kanji_target == pytest.approx(0.15)
    assert mix.jlpt_mix == {"n5": 0.15, "n4": 0.30, "n3": 0.30, "n2": 0.20, "n1": 0.05}


def test_midpoint_between_1_and_2() -> None:
    mix = stretch.interpolate(1.5)
    assert mix.unknown_kanji_target == pytest.approx(0.075)
    assert mix.jlpt_mix == {"n5": 0.40, "n4": 0.35, "n3": 0.20, "n2": 0.05, "n1": 0.0}


def test_midpoint_between_0_and_1_rounds_to_whole_percent() -> None:
    mix = stretch.interpolate(0.5)
    assert mix.unknown_kanji_target == pytest.approx(0.035)
    # Raw shares are 60 / 32.5 / 7.5 / 0 / 0 -- n4 and n3 tie on a 0.5
    # fractional remainder, broken by level order (n4 before n3), so n4
    # gets the extra point.
    assert mix.jlpt_mix == {"n5": 0.60, "n4": 0.33, "n3": 0.07, "n2": 0.0, "n1": 0.0}


@pytest.mark.parametrize("d", [0, 0.1, 0.3, 0.5, 0.7, 1, 1.1, 1.3, 1.5, 1.7, 1.9, 2, 2.2, 2.5, 2.9, 3])
def test_mix_always_sums_to_exactly_one(d: float) -> None:
    mix = stretch.interpolate(d)
    assert sum(mix.jlpt_mix.values()) == pytest.approx(1.0, abs=1e-9)


def test_unknown_kanji_rounds_to_one_decimal_percent() -> None:
    mix = stretch.interpolate(1.3)
    # 5 + 0.3 * (10 - 5) = 6.5%
    assert mix.unknown_kanji_target == pytest.approx(0.065)


def test_resolve_clamps_before_interpolating() -> None:
    assert stretch.resolve(10) == stretch.interpolate(stretch.D_MAX)
    assert stretch.resolve(-10) == stretch.interpolate(stretch.D_MIN)


# --- the after-session rule ---------------------------------------------


def test_harder_needs_both_conditions() -> None:
    assert stretch.decide_reason(helps_per_100_words=3.0, comprehension_percent=80.0) == "harder"
    # Helps clears the bar but comprehension does not.
    assert stretch.decide_reason(helps_per_100_words=3.0, comprehension_percent=79.9) == "unchanged"
    # Comprehension clears the bar but helps does not.
    assert stretch.decide_reason(helps_per_100_words=3.1, comprehension_percent=80.0) == "unchanged"


def test_easier_needs_either_condition() -> None:
    assert stretch.decide_reason(helps_per_100_words=8.1, comprehension_percent=100.0) == "easier"
    assert stretch.decide_reason(helps_per_100_words=0.0, comprehension_percent=59.9) == "easier"


def test_boundaries_are_inclusive_toward_harder_and_comfortable() -> None:
    # Exactly at the harder thresholds.
    assert stretch.decide_reason(helps_per_100_words=3.0, comprehension_percent=80.0) == "harder"
    # Exactly at the easier thresholds: NOT easier (helps must exceed 8,
    # comprehension must fall *below* 60 -- both boundaries belong to the
    # comfortable middle, per the brief's ">" / "<").
    assert stretch.decide_reason(helps_per_100_words=8.0, comprehension_percent=60.0) == "unchanged"


def test_middle_ground_is_unchanged() -> None:
    assert stretch.decide_reason(helps_per_100_words=5.0, comprehension_percent=70.0) == "unchanged"


def test_next_d_steps_and_clamps() -> None:
    assert stretch.next_d(1.0, "harder") == pytest.approx(1.1)
    assert stretch.next_d(1.0, "easier") == pytest.approx(0.9)
    assert stretch.next_d(1.0, "unchanged") == pytest.approx(1.0)
    # Clamped at the top/bottom of the range.
    assert stretch.next_d(stretch.D_MAX, "harder") == pytest.approx(stretch.D_MAX)
    assert stretch.next_d(stretch.D_MIN, "easier") == pytest.approx(stretch.D_MIN)


def test_next_d_does_not_drift_on_repeated_steps() -> None:
    d = 1.0
    for _ in range(20):  # far more than enough to reach D_MAX from 1.0
        d = stretch.next_d(d, "harder")
    assert d == pytest.approx(stretch.D_MAX)


def test_adjust_bundles_decide_and_step() -> None:
    result = stretch.adjust(1.0, helps_per_100_words=2.0, comprehension_percent=90.0)
    assert result.d_before == 1.0
    assert result.d_after == pytest.approx(1.1)
    assert result.reason == "harder"


def test_adjust_records_unchanged_without_moving_d() -> None:
    result = stretch.adjust(1.0, helps_per_100_words=5.0, comprehension_percent=70.0)
    assert result.d_after == result.d_before == 1.0
    assert result.reason == "unchanged"


# --- describe_mix ---------------------------------------------------------


def test_describe_mix_at_the_start() -> None:
    text = stretch.describe_mix(stretch.interpolate(stretch.D_START))
    assert text == "Now: N5 50 · N4 35 · N3 15 · 5 % unknown kanji"


def test_describe_mix_omits_zero_levels() -> None:
    text = stretch.describe_mix(stretch.interpolate(0))
    assert text == "Now: N5 70 · N4 30 · 2 % unknown kanji"


def test_describe_mix_keeps_one_decimal_when_present() -> None:
    text = stretch.describe_mix(stretch.interpolate(1.3))
    assert "6.5 % unknown kanji" in text
