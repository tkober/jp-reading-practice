"""The three help prompt frames (issue #10): the whole text and the target
are always included, the word limits and rules are stated, and the frame
cannot be mistaken for the generation frame's own topic-override wording."""

from __future__ import annotations

from app.help_prompts import (
    build_explain_grammar_instructions,
    build_explain_word_instructions,
    build_translate_sentence_instructions,
)

TEXT = "水曜日です。猫が水を飲みます。"
SENTENCE = "猫が水を飲みます。"


def test_explain_word_includes_text_target_and_word_limit() -> None:
    text = build_explain_word_instructions(text=TEXT, surface="飲みます", sentence=SENTENCE)

    assert TEXT in text
    assert SENTENCE in text
    assert "飲みます" in text
    assert "dictionary (base) form" in text
    assert "80 words" in text
    assert "No markdown" in text or "no markdown" in text
    assert "romaji" in text


def test_translate_sentence_asks_for_translation_then_a_misreading_note() -> None:
    text = build_translate_sentence_instructions(text=TEXT, sentence=SENTENCE)

    assert TEXT in text
    assert SENTENCE in text
    assert "translation" in text
    assert "misread" in text or "misparse" in text
    assert "60 words" in text


def test_explain_grammar_asks_for_one_to_three_points() -> None:
    text = build_explain_grammar_instructions(text=TEXT, sentence=SENTENCE)

    assert TEXT in text
    assert SENTENCE in text
    assert "1 to 3 grammar points" in text
    assert "120 words" in text


def test_all_three_share_the_same_tutor_role_and_rules() -> None:
    for prompt in (
        build_explain_word_instructions(text=TEXT, surface="猫", sentence=SENTENCE),
        build_translate_sentence_instructions(text=TEXT, sentence=SENTENCE),
        build_explain_grammar_instructions(text=TEXT, sentence=SENTENCE),
    ):
        assert "patient" in prompt
        assert "English-speaking" in prompt
        assert "Never use romaji" in prompt
        assert "Quote Japanese exactly as written" in prompt
