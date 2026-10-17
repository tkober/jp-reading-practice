"""Generation presets: easy / stretch / challenge (issue #8).

Each preset is a starting point for the three level knobs text generation
cares about -- the unknown-kanji budget, the JLPT mix target, and (unless the
topic or the caller overrides it) the writing style -- plus the three length
presets, which are independent of difficulty.

Stretch is deliberately static here: the brief for issue #13 is to make it
*adaptive* to the learner's own progress. Keeping it a plain constant now
means #13 has one obvious place to change, rather than a design that has to
be undone first.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import JlptMixTarget

PresetName = str  # "easy" | "stretch" | "challenge", validated at the API boundary
LengthName = str  # "short" | "medium" | "long"


@dataclass(frozen=True)
class Preset:
    """One difficulty preset.

    `style_default` is `None` for every preset here -- the brief: "Style
    default comes from the topic unless given", i.e. the *topic's*
    `default_style` wins unless the request itself names a style. A preset
    could in principle pin its own style (kept as a field so that stays
    possible without another schema change), but none of the three does
    today.
    """

    unknown_kanji_target: float
    jlpt_mix: JlptMixTarget
    style_default: str | None = None


PRESETS: dict[PresetName, Preset] = {
    "easy": Preset(
        unknown_kanji_target=0.02,
        jlpt_mix=JlptMixTarget(n5=0.70, n4=0.30),
    ),
    "stretch": Preset(
        unknown_kanji_target=0.05,
        jlpt_mix=JlptMixTarget(n5=0.50, n4=0.35, n3=0.15),
    ),
    "challenge": Preset(
        unknown_kanji_target=0.10,
        jlpt_mix=JlptMixTarget(n5=0.30, n4=0.35, n3=0.25, n2=0.10),
    ),
}

#: Target length in characters, ±10% (see `prompts.py`), keyed independently
#: of the difficulty preset -- a learner picks a length and a difficulty
#: separately.
LENGTHS: dict[LengthName, int] = {
    "short": 300,
    "medium": 600,
    "long": 1000,
}


def preset_names() -> list[str]:
    return list(PRESETS)


def length_names() -> list[str]:
    return list(LENGTHS)


def get_preset(name: str) -> Preset | None:
    return PRESETS.get(name)


def get_length(name: str) -> int | None:
    return LENGTHS.get(name)
