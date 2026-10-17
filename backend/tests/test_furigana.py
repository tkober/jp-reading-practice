"""Tokenisation, paragraph splitting and the furigana rule (issue #7).

`is_reading_composed` is the one function the brief asks for "many tests"
on -- the cases below are the ones the issue names explicitly, plus a few
edge cases the algorithm itself needs covered (unknown kanji, no reading at
all, a non-kanji/non-kana run).
"""

from __future__ import annotations

from app import furigana as fg

# --- tokenisation --------------------------------------------------------


def test_tokenizes_the_fixture_title_with_per_kanji_readings() -> None:
    tokens = fg.tokenize_paragraph("金沢の雨の日")

    assert [t.surface for t in tokens] == ["金沢", "の", "雨", "の", "日"]
    assert [t.reading for t in tokens] == ["かなざわ", "の", "あめ", "の", "ひ"]
    assert [t.is_word for t in tokens] == [True, False, True, False, True]


def test_proper_noun_lemma_is_the_written_form_not_unidics_katakana_lemma() -> None:
    """unidic's own `lemma` feature for 金沢 is its katakana pronunciation
    (カナザワ) rather than the written form -- `orthBase`, which `lemma`
    comes from since #7's review, is "金沢" regardless of part of speech."""
    tokens = fg.tokenize_paragraph("金沢")

    assert tokens[0].lemma == "金沢"
    assert tokens[0].lemma_reading == "かなざわ"
    assert tokens[0].alt_lemma == "カナザワ"


def test_inflected_verb_lemma_is_the_dictionary_form() -> None:
    tokens = fg.tokenize_paragraph("食べました。")

    verb = next(t for t in tokens if t.surface == "食べ")
    assert verb.lemma == "食べる"
    assert verb.lemma_reading == "たべる"
    assert verb.pos == "動詞"


# --- base form (orthBase/kanaBase/lemma) -- see furigana._base_form -------


def test_base_form_reading_is_not_the_inflected_surfaces_own_reading() -> None:
    """行き's own (surface) reading is いき -- but a lookup for the base
    form 行く needs いく, not いき, or every lookup against an external
    word list keyed by (行く, いく) misses."""
    [token] = fg.tokenize_paragraph("行き")

    assert token.surface == "行き"
    assert token.reading == "いき"  # the surface's own reading, for ruby
    assert token.lemma == "行く"
    assert token.lemma_reading == "いく"  # the base form's own reading
    assert token.alt_lemma is None  # unidic's lemma feature agrees here


def test_base_form_prefers_written_form_over_unidics_different_headword() -> None:
    """撮っ (撮る, "to photograph") must not be looked up as 取る ("to
    take") just because unidic's own `lemma` feature names that different
    verb -- same reading, wrong word. `alt_lemma` carries it anyway (as the
    second, fallback candidate `analysis.lookup_candidates` tries), but the
    primary `lemma` is `orthBase`, "撮る"."""
    [token] = fg.tokenize_paragraph("撮っ")

    assert token.lemma == "撮る"
    assert token.lemma_reading == "とる"
    assert token.alt_lemma == "取る"


def test_base_form_falls_back_to_the_modern_kana_spelling_not_unidics_kanji_lemma() -> None:
    """unidic's own `lemma` for several everyday verbs is a kanji spelling
    nobody actually writes any more (居る, 出来る) -- `orthBase` gives the
    modern kana spelling that JLPT lists/JMdict/the known-vocabulary set
    actually use."""
    iru = fg.tokenize_paragraph("いました")[0]  # いる, continuative + ました
    assert iru.surface == "い"
    assert iru.lemma == "いる"
    assert iru.alt_lemma == "居る"

    dekiru = fg.tokenize_paragraph("できました")[0]  # できる, continuative + ました
    assert dekiru.surface == "でき"
    assert dekiru.lemma == "できる"
    assert dekiru.alt_lemma == "出来る"


def test_base_form_of_a_kana_written_noun_keeps_its_kanji_lemma_as_a_fallback() -> None:
    """こと (base form has no kanji at all) still needs a way to match a
    kanji-headword list entry (事) -- `alt_lemma` is that fallback, tried
    only when the written base form alone is not found (see
    `analysis.lookup_candidates`)."""
    [token] = fg.tokenize_paragraph("こと")

    assert token.lemma == "こと"
    assert token.lemma_reading == "こと"
    assert token.alt_lemma == "事"


def test_particles_and_auxiliaries_and_punctuation_are_not_words() -> None:
    tokens = fg.tokenize_paragraph("彼は3時に来た。")

    by_surface = {t.surface: t for t in tokens}
    assert by_surface["は"].is_word is False  # 助詞
    assert by_surface["た"].is_word is False  # 助動詞
    assert by_surface["。"].is_word is False  # 補助記号
    # Numbers count, per the brief.
    assert by_surface["3"].is_word is True


def test_ruby_segments_split_okurigana_off_a_single_kanji_word() -> None:
    tokens = fg.tokenize_paragraph("食べる")

    [token] = tokens
    assert [(s.base, s.reading) for s in token.segments] == [("食", "た"), ("べる", None)]


def test_surface_readings_overrides_the_dictionary_reading_for_私() -> None:
    """unidic's own reading for 私 is ワタクシ, which is defensible and not
    what a textbook teaches -- `_SURFACE_READINGS` (ported from
    jp-conversation-practice's furigana.py) overrides it."""
    tokens = fg.tokenize_paragraph("私")

    [token] = tokens
    assert token.reading == "わたし"


def test_split_word_falls_back_to_one_ruby_when_the_kana_does_not_line_up() -> None:
    """A contrived mismatch (not reachable through real tokenizer output,
    but the fallback `_split_word` itself promises) still returns exactly
    one ruby over the whole word rather than raising or guessing."""
    segments = fg._split_word("食べる", "zzz")

    assert segments == [fg.RubySegment(base="食べる", reading="zzz")]


def test_tokenizer_degrades_gracefully_when_the_tagger_cannot_load(monkeypatch) -> None:
    monkeypatch.setattr(fg, "_tagger", lambda: None)

    tokens = fg.tokenize_paragraph("金沢の雨の日")

    assert len(tokens) == 1
    assert tokens[0].surface == "金沢の雨の日"
    assert tokens[0].is_word is False
    assert tokens[0].segments == [fg.RubySegment(base="金沢の雨の日")]


def test_tokenizer_returns_nothing_for_empty_text() -> None:
    assert fg.tokenize_paragraph("") == []


# --- paragraph splitting --------------------------------------------------


def test_split_paragraphs_breaks_on_blank_lines_and_rejoins_wrapped_lines() -> None:
    text = "金沢は\n静かだった。\n\n雨の日だった。"

    assert fg.split_paragraphs(text) == ["金沢は静かだった。", "雨の日だった。"]


def test_split_paragraphs_drops_blank_paragraphs() -> None:
    assert fg.split_paragraphs("\n\n  \n\n金沢\n\n") == ["金沢"]


# --- the furigana rule: is_reading_composed -------------------------------


def test_irregular_reading_is_not_composed_even_though_both_kanji_are_known() -> None:
    """今日 reads きょう, which follows from neither 今 (こん/いま) nor 日's
    own readings -- an irregular reading needs furigana regardless of
    whether its kanji are individually known."""
    known = {"今": frozenset({"こん", "いま"}), "日": frozenset({"にち", "じつ", "ひ", "か"})}

    assert fg.is_reading_composed("今日", "きょう", known) is False


def test_onyomi_compound_composes_directly() -> None:
    known = {"学": frozenset({"がく", "まな"}), "生": frozenset({"せい", "しょう"})}

    assert fg.is_reading_composed("学生", "がくせい", known) is True


def test_unknown_kanji_never_composes() -> None:
    """緒 missing from `known` entirely (not just a different reading) must
    fail -- there is no candidate reading to try at all."""
    known = {"一": frozenset({"いち"})}

    assert fg.is_reading_composed("一緒", "いっしょ", known) is False


def test_verb_stem_plus_okurigana_plus_kunyomi_composes() -> None:
    """飲み物: 飲's kun'yomi の (already bare of its okurigana み, per
    kanji-trainer's own WaniKani-sourced data) has to line up with the
    surface's own み before 物's もの."""
    known = {"飲": frozenset({"の"}), "物": frozenset({"ぶつ", "もつ", "もの"})}

    assert fg.is_reading_composed("飲み物", "のみもの", known) is True


def test_rendaku_is_tolerated_at_a_kanji_boundary() -> None:
    """手紙: 紙's known kun'yomi is かみ, but it voices to がみ after 手."""
    known = {"手": frozenset({"て"}), "紙": frozenset({"かみ"})}

    assert fg.is_reading_composed("手紙", "てがみ", known) is True


def test_gemination_is_tolerated_at_a_kanji_boundary() -> None:
    """学校: 学's known on'yomi がく loses its く to a geminate っ before 校."""
    known = {"学": frozenset({"がく"}), "校": frozenset({"こう"})}

    assert fg.is_reading_composed("学校", "がっこう", known) is True


def test_no_reading_never_composes() -> None:
    assert fg.is_reading_composed("日", "", {"日": frozenset({"ひ"})}) is False


def test_mismatched_okurigana_does_not_compose() -> None:
    """食べる read たべる with 食's reading claimed as た succeeds, but
    claiming the word is instead read たべた (okurigana that does not match
    the surface's べる) must fail."""
    known = {"食": frozenset({"た"})}

    assert fg.is_reading_composed("食べる", "たべる", known) is True
    assert fg.is_reading_composed("食べる", "たべた", known) is False
