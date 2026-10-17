"""Presets: easy / stretch / challenge targets, and the length constants
(issue #8)."""

from __future__ import annotations

from app import presets


def test_easy_preset_matches_the_brief() -> None:
    preset = presets.get_preset("easy")
    assert preset is not None
    assert preset.unknown_kanji_target == 0.02
    assert preset.jlpt_mix.n5 == 0.70
    assert preset.jlpt_mix.n4 == 0.30
    assert preset.jlpt_mix.n3 == 0.0


def test_stretch_preset_matches_the_brief() -> None:
    preset = presets.get_preset("stretch")
    assert preset is not None
    assert preset.unknown_kanji_target == 0.05
    assert preset.jlpt_mix.n5 == 0.50
    assert preset.jlpt_mix.n4 == 0.35
    assert preset.jlpt_mix.n3 == 0.15


def test_challenge_preset_matches_the_brief() -> None:
    preset = presets.get_preset("challenge")
    assert preset is not None
    assert preset.unknown_kanji_target == 0.10
    assert preset.jlpt_mix.n5 == 0.30
    assert preset.jlpt_mix.n4 == 0.35
    assert preset.jlpt_mix.n3 == 0.25
    assert preset.jlpt_mix.n2 == 0.10


def test_every_preset_mix_sums_to_one() -> None:
    for name in presets.preset_names():
        preset = presets.get_preset(name)
        assert preset is not None
        total = (
            preset.jlpt_mix.n5
            + preset.jlpt_mix.n4
            + preset.jlpt_mix.n3
            + preset.jlpt_mix.n2
            + preset.jlpt_mix.n1
        )
        assert abs(total - 1.0) < 1e-9


def test_unknown_preset_is_none() -> None:
    assert presets.get_preset("nonsense") is None


def test_lengths_match_the_brief() -> None:
    assert presets.get_length("short") == 300
    assert presets.get_length("medium") == 600
    assert presets.get_length("long") == 1000
    assert presets.get_length("nonsense") is None
