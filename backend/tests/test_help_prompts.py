"""The three help prompt frames (issue #10) plus the tutor chat's own
(issue #11): the whole text and the target are always included, the word
limits and rules are stated, and the frame cannot be mistaken for the
generation frame's own topic-override wording."""

from __future__ import annotations

from app.help_prompts import (
    build_explain_grammar_instructions,
    build_explain_word_instructions,
    build_translate_sentence_instructions,
    build_tutor_messages,
    build_tutor_system_prompt,
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


# --- Tutor chat (issue #11) --------------------------------------------------


def test_tutor_system_prompt_includes_text_and_rules() -> None:
    prompt = build_tutor_system_prompt(text=TEXT)

    assert TEXT in prompt
    assert "patient" in prompt  # shares _ROLE with the other three
    assert "120 words" in prompt
    assert "sentence by sentence" in prompt
    assert "redirect" in prompt.lower() or "steering" in prompt.lower()


def test_tutor_messages_start_with_the_system_frame() -> None:
    messages = build_tutor_messages(text=TEXT, history=[], question="猫は何をしていますか？")

    assert messages[0]["role"] == "system"
    assert TEXT in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "猫は何をしていますか？"}
    assert len(messages) == 2  # system + the one new question, no history yet


def test_tutor_messages_include_history_oldest_first_between_system_and_new_question() -> None:
    history = [("user", "猫は何をしていますか？"), ("assistant", "猫は水を飲んでいます。")]
    messages = build_tutor_messages(text=TEXT, history=history, question="なぜ？")

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1] == {"role": "user", "content": "猫は何をしていますか？"}
    assert messages[2] == {"role": "assistant", "content": "猫は水を飲んでいます。"}
    assert messages[3] == {"role": "user", "content": "なぜ？"}


def test_tutor_messages_prefixes_the_new_question_with_the_focus_sentence() -> None:
    messages = build_tutor_messages(
        text=TEXT, history=[], question="これは何の意味ですか？", focus_sentence=SENTENCE
    )

    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == (
        f"About this sentence: {SENTENCE}\n\nこれは何の意味ですか？"
    )


def test_tutor_messages_never_re_adds_a_past_turns_own_focus_prefix() -> None:
    # Only the *new* question gets the "About this sentence: ..." prefix --
    # a past turn is sent back exactly as it was stored, even if it had its
    # own focus at the time (that context already shaped the answer stored
    # right after it).
    history = [("user", "これは何の意味ですか？"), ("assistant", "...")]
    messages = build_tutor_messages(text=TEXT, history=history, question="もう一つ質問です。")

    assert messages[1] == {"role": "user", "content": "これは何の意味ですか？"}
