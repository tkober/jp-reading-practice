"""Stretch's adaptive difficulty (issue #13): pure interpolation and the
after-session rule that moves it.

Nothing here touches the database -- same split as `stats_math.py`/
`api/stats.py`: every *decision* (what a given difficulty `d` resolves to,
which way a finished session should nudge it) lives here, unit-tested on its
own (`tests/test_stretch.py`); `app/stretch_store.py` is the only module that
reads or writes the `stretch_adjustments` table, and `api/texts.py`/
`api/sessions.py`/`api/presets.py` are the thin HTTP-layer glue between the
two.

**The scale.** `d` is one number along a 0..3 anchor table (the concept's
own four rows): 0 is "easy", 1 is Stretch's own starting point (and exactly
the static mix issue #8 shipped with), 2 is "challenge", 3 is a fourth,
harder-still anchor that only Stretch's own adaptation ever reaches *toward*
-- `D_MAX` (2.5) keeps it from ever fully reaching 3. `easy`/`challenge`
call `interpolate()` at exactly `d=0`/`d=2`, which is why their numbers here
match `presets.PRESETS` exactly (see `tests/test_stretch.py`); only
Stretch's own `d` ever moves, by `D_STEP` per qualifying session, clamped to
`[D_MIN, D_MAX]`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Anchor presets in percent-space, keyed by the integer `d` each names --
#: matches `presets.PRESETS`'s "easy"/"challenge" numbers exactly at d=0/2,
#: and the pre-#13 static "stretch" preset exactly at d=1.
_ANCHOR_UNKNOWN_KANJI_PERCENT: dict[int, float] = {0: 2.0, 1: 5.0, 2: 10.0, 3: 15.0}
_ANCHOR_JLPT_MIX_PERCENT: dict[int, dict[str, float]] = {
    0: {"n5": 70.0, "n4": 30.0, "n3": 0.0, "n2": 0.0, "n1": 0.0},
    1: {"n5": 50.0, "n4": 35.0, "n3": 15.0, "n2": 0.0, "n1": 0.0},
    2: {"n5": 30.0, "n4": 35.0, "n3": 25.0, "n2": 10.0, "n1": 0.0},
    3: {"n5": 15.0, "n4": 30.0, "n3": 30.0, "n2": 20.0, "n1": 5.0},
}
#: Display/tie-break order, easiest level first -- used both by the
#: largest-remainder rounding below (deterministic tie-break) and by
#: `describe_mix`'s own text.
_LEVEL_ORDER: tuple[str, ...] = ("n5", "n4", "n3", "n2", "n1")

#: Stretch's own difficulty starts here and is clamped to this range,
#: stepping by this much per qualifying session (issue #13 brief).
D_START = 1.0
D_MIN = 0.5
D_MAX = 2.5
D_STEP = 0.1

#: The after-session rule's thresholds (issue #13 brief): "harder" needs
#: *both* conditions, "easier" needs *either* one, otherwise "unchanged".
#: `helps_per_100_words` is the session's own number (`app.helps`);
#: `comprehension_percent` is 0..100, same convention as `stats_math`'s own
#: comprehension numbers.
HARDER_HELPS_MAX = 3.0
HARDER_COMPREHENSION_MIN = 80.0
EASIER_HELPS_MIN = 8.0
EASIER_COMPREHENSION_MAX = 60.0

AdjustmentReason = Literal["harder", "easier", "unchanged"]


def clamp_d(d: float) -> float:
    return max(D_MIN, min(D_MAX, d))


@dataclass(frozen=True)
class StretchMix:
    """One resolved mix at some difficulty `d` -- `unknown_kanji_target` a
    fraction (0..1), one-decimal-percent precision; `jlpt_mix` fractions
    (0..1) rounded to whole percent, always summing to exactly 1.0 (largest-
    remainder, see `_round_mix_percent`). Same shape as `presets.Preset`'s
    own two fields, so either can feed `TextTargets` directly."""

    unknown_kanji_target: float
    jlpt_mix: dict[str, float]


def _round_mix_percent(raw: dict[str, float]) -> dict[str, int]:
    """Round each share to a whole percent so the five sum to exactly 100 --
    rounding each value on its own can drift the total by a point either
    way; this hands the extra point(s) to the largest fractional remainders
    instead (ties broken by `_LEVEL_ORDER`, easiest level first)."""
    floors = {level: int(value) for level, value in raw.items()}
    total = round(sum(raw.values()))
    remainder = total - sum(floors.values())
    by_remainder = sorted(
        _LEVEL_ORDER,
        key=lambda level: (-(raw[level] - floors[level]), _LEVEL_ORDER.index(level)),
    )
    result = dict(floors)
    for level in by_remainder[:remainder]:
        result[level] += 1
    return result


def interpolate(d: float) -> StretchMix:
    """Linear interpolation between the two integer anchors `d` sits
    between. `d` is not clamped here -- `easy`/`challenge` call this at
    exactly 0/2; Stretch's own adaptive value is clamped (`clamp_d`) before
    it ever reaches here, by the caller."""
    lower = max(0, min(3, int(d // 1)))
    upper = min(3, lower + 1)
    t = (d - lower) if upper > lower else 0.0

    unknown_kanji_percent = round(
        _ANCHOR_UNKNOWN_KANJI_PERCENT[lower]
        + t * (_ANCHOR_UNKNOWN_KANJI_PERCENT[upper] - _ANCHOR_UNKNOWN_KANJI_PERCENT[lower]),
        1,
    )
    raw_mix = {
        level: _ANCHOR_JLPT_MIX_PERCENT[lower][level]
        + t * (_ANCHOR_JLPT_MIX_PERCENT[upper][level] - _ANCHOR_JLPT_MIX_PERCENT[lower][level])
        for level in _LEVEL_ORDER
    }
    mix_percent = _round_mix_percent(raw_mix)

    return StretchMix(
        unknown_kanji_target=round(unknown_kanji_percent / 100, 4),
        jlpt_mix={level: share / 100 for level, share in mix_percent.items()},
    )


def resolve(d: float) -> StretchMix:
    """`interpolate(clamp_d(d))` -- what generation and `GET /api/presets`
    actually want: a `d` that is always in range, regardless of where it
    came from (a fresh `D_START`, or a stored row from before clamping
    changed, which should not happen but costs nothing to guard)."""
    return interpolate(clamp_d(d))


def describe_mix(mix: StretchMix) -> str:
    """"Now: N5 45 · N4 35 · N3 18 · N2 2 · 5.5 % unknown kanji" -- the
    Stats page's one-line summary of Stretch's current mix (issue #13
    brief). Levels at 0% are left out (Stretch's own anchor table never
    reaches N1, see the module docstring), so the common case stays short."""
    parts = [
        f"{level.upper()} {round(mix.jlpt_mix.get(level, 0.0) * 100)}"
        for level in _LEVEL_ORDER
        if mix.jlpt_mix.get(level, 0.0) > 0
    ]
    unknown_percent = round(mix.unknown_kanji_target * 100, 1)
    unknown_text = f"{unknown_percent:g}"
    return f"Now: {' · '.join(parts)} · {unknown_text} % unknown kanji"


def decide_reason(helps_per_100_words: float, comprehension_percent: float) -> AdjustmentReason:
    """"harder" needs both low helps and high comprehension; "easier" needs
    either high helps or low comprehension; otherwise "unchanged" -- see the
    module-level constants for the exact thresholds."""
    if helps_per_100_words <= HARDER_HELPS_MAX and comprehension_percent >= HARDER_COMPREHENSION_MIN:
        return "harder"
    if helps_per_100_words > EASIER_HELPS_MIN or comprehension_percent < EASIER_COMPREHENSION_MAX:
        return "easier"
    return "unchanged"


def next_d(d_before: float, reason: AdjustmentReason) -> float:
    """`d_before` stepped by `D_STEP` in the rule's direction and clamped --
    `round(..., 2)` keeps repeated +/-0.1 steps from drifting on binary
    floats (e.g. `1.0 - 0.1 == 0.8999999999999999`)."""
    if reason == "harder":
        return clamp_d(round(d_before + D_STEP, 2))
    if reason == "easier":
        return clamp_d(round(d_before - D_STEP, 2))
    return d_before


@dataclass(frozen=True)
class StretchAdjustmentResult:
    """What one finished, qualifying session does to Stretch -- `reason` is
    recorded even when `d_after == d_before` ("unchanged" still counts as a
    row, per the brief, so the history shows every session that was
    considered, not only the ones that moved something)."""

    d_before: float
    d_after: float
    reason: AdjustmentReason


def adjust(
    d_before: float, *, helps_per_100_words: float, comprehension_percent: float
) -> StretchAdjustmentResult:
    """The one rule, applied: `decide_reason` then `next_d`, bundled as what
    `api/sessions.py` actually needs to record one `stretch_adjustments`
    row."""
    reason = decide_reason(helps_per_100_words, comprehension_percent)
    return StretchAdjustmentResult(
        d_before=d_before, d_after=next_d(d_before, reason), reason=reason
    )
