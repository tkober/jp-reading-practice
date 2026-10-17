"""`split_sentences()`/`find_sentence()` (issue #10): sentence boundaries
for "Translate sentence"/"Explain grammar", including quotes and a
paragraph without a final 。."""

from __future__ import annotations

from app.sentences import find_sentence, split_sentences


def _pairs(*surfaces: str) -> list[tuple[str, str]]:
    """`(token_id, surface)` pairs with ids `"0-0"`, `"0-1"`, ... -- the
    paragraph index is irrelevant to the splitter itself, only to the key
    format, so every test here uses paragraph 0."""
    return [(f"0-{i}", surface) for i, surface in enumerate(surfaces)]


def test_splits_two_simple_sentences() -> None:
    tokens = _pairs("水", "を", "飲む", "。", "猫", "が", "いる", "。")
    sentences = split_sentences(0, tokens)

    assert [s.key for s in sentences] == ["0-0", "0-1"]
    assert [s.text for s in sentences] == ["水を飲む。", "猫がいる。"]
    assert sentences[0].token_ids == ["0-0", "0-1", "0-2", "0-3"]
    assert sentences[1].token_ids == ["0-4", "0-5", "0-6", "0-7"]


def test_paragraph_without_a_final_ender_still_gets_a_trailing_sentence() -> None:
    tokens = _pairs("水", "を", "飲む", "。", "まだ", "書いている")
    sentences = split_sentences(0, tokens)

    assert [s.text for s in sentences] == ["水を飲む。", "まだ書いている"]
    assert sentences[1].key == "0-1"


def test_empty_paragraph_has_no_sentences() -> None:
    assert split_sentences(0, []) == []


def test_a_closing_quote_directly_after_the_ender_stays_in_the_same_sentence() -> None:
    # 「そうだ。」と言った。 -- the 」 closes the quote right after 。, and
    # must not start a new (empty) sentence of its own.
    tokens = _pairs("「", "そう", "だ", "。", "」", "と", "言った", "。")
    sentences = split_sentences(0, tokens)

    assert [s.text for s in sentences] == ["「そうだ。」", "と言った。"]
    assert sentences[0].token_ids == ["0-0", "0-1", "0-2", "0-3", "0-4"]


def test_a_closing_bracket_after_a_different_quote_mark_also_stays() -> None:
    tokens = _pairs("『", "元気", "か", "？", "』", "彼", "は", "聞いた", "。")
    sentences = split_sentences(0, tokens)

    assert [s.text for s in sentences] == ["『元気か？』", "彼は聞いた。"]


def test_an_ascii_question_mark_also_ends_a_sentence() -> None:
    tokens = _pairs("元気", "です", "か", "!", "はい", "。")
    sentences = split_sentences(0, tokens)

    assert [s.text for s in sentences] == ["元気ですか!", "はい。"]


def test_find_sentence_locates_the_sentence_a_token_belongs_to() -> None:
    tokens = _pairs("水", "を", "飲む", "。", "猫", "が", "いる", "。")

    sentence = find_sentence(0, tokens, "0-5")

    assert sentence is not None
    assert sentence.key == "0-1"
    assert sentence.text == "猫がいる。"


def test_find_sentence_returns_none_for_an_unknown_token() -> None:
    tokens = _pairs("水", "を", "飲む", "。")
    assert find_sentence(0, tokens, "no-such-token") is None


def test_sentence_keys_use_the_given_paragraph_index() -> None:
    tokens = [(f"2-{i}", surface) for i, surface in enumerate(["水", "。"])]
    sentences = split_sentences(2, tokens)
    assert sentences[0].key == "2-0"
