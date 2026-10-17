"""`analyze()` -- pure, no MCP (issue #7). Metrics, JLPT mix, and the
furigana rule wired into actual tokens (the rule itself has its own, much
larger test file, `test_furigana.py`)."""

from __future__ import annotations

from app import kanji_trainer as kt
from app.analysis import analyze, collect_lemmas, lookup_candidates
from app.furigana import tokenize_paragraph
from app.known_set import KnownSet


def _jlpt(text: str, reading: str | None, jlpt: int | None, kanji_jlpt: dict[str, int | None]) -> kt.JlptLevelResult:
    return kt.JlptLevelResult(
        text=text,
        reading=reading,
        jlpt=jlpt,
        kanji=[kt.KanjiCharacterLevel(character=c, jlpt=j) for c, j in kanji_jlpt.items()],
    )


# --- metrics --------------------------------------------------------------


def test_metrics_on_a_small_fixed_text() -> None:
    # Tokenizes as 金沢/の/雨/の/日/、/12/日間/。 -- 6 kanji occurrences
    # (金,沢,雨,日,日,間; 日 occurs once alone and once inside 日間), 5
    # content words (金沢,雨,日,12,日間). 10 countable characters; the 、
    # and 。 do not count.
    text = "金沢の雨の日、12日間。"
    known = KnownSet(kanji={"金": frozenset(), "沢": frozenset()})

    result = analyze(text, known, {})

    assert result.metrics.characters == 10
    assert result.metrics.words == 5
    assert result.metrics.kanji_total == 6
    assert result.metrics.kanji_unknown == 4  # every 雨/日/日/間, not 金/沢
    assert result.metrics.unknown_kanji_share == 4 / 6


def test_characters_excludes_punctuation_and_whitespace_but_counts_digits_and_latin() -> None:
    known = KnownSet()
    result = analyze("Aさん は 3 回 来た。", known, {})

    # A, さ,ん,は,3,回,来,た = 8; the two spaces and the full stop do not count.
    assert result.metrics.characters == 8


def test_words_counts_is_word_tokens_only() -> None:
    known = KnownSet()
    result = analyze("彼は3時に来た。", known, {})

    # 彼(代名詞), 3(名詞-数詞), 時(名詞), 来(動詞) are words; は(助詞), に(助詞),
    # た(助動詞), 。(補助記号) are not.
    assert result.metrics.words == 4


def test_kanji_total_counts_occurrences_not_distinct_characters() -> None:
    known = KnownSet()
    result = analyze("日々の日記", known, {})  # 日 occurs twice, 々/記 once each

    assert result.metrics.kanji_total == 3  # 日, 日, 記 -- 々 is not kanji itself


def test_unknown_kanji_share_is_zero_when_the_text_has_no_kanji() -> None:
    known = KnownSet()
    result = analyze("ありがとう", known, {})

    assert result.metrics.kanji_total == 0
    assert result.metrics.unknown_kanji_share == 0.0


# --- JLPT mix --------------------------------------------------------------


def test_jlpt_mix_shares_content_words_across_levels_and_unlisted() -> None:
    known = KnownSet()
    text = "日\n\n月"  # two one-paragraph single-kanji nouns, both content words
    jlpt_lookup = {
        ("日", "ひ"): _jlpt("日", "ひ", 5, {"日": 5}),
        ("月", "つき"): _jlpt("月", "つき", None, {"月": None}),
    }

    result = analyze(text, known, jlpt_lookup)

    assert result.metrics.jlpt_mix.n5 == 0.5
    assert result.metrics.jlpt_mix.unlisted == 0.5
    assert result.metrics.jlpt_mix.n4 == 0.0


def test_jlpt_mix_is_all_zero_with_no_content_words() -> None:
    known = KnownSet()
    result = analyze("の", known, {})  # a lone particle: no content words

    assert result.metrics.jlpt_mix.n5 == 0.0
    assert result.metrics.jlpt_mix.unlisted == 0.0


def test_token_jlpt_and_per_kanji_jlpt_come_from_the_lookup() -> None:
    known = KnownSet()
    jlpt_lookup = {("食べる", "たべる"): _jlpt("食べる", "たべる", 5, {"食": 5})}

    result = analyze("食べる", known, jlpt_lookup)

    [token] = result.paragraphs[0].tokens
    assert token.jlpt == 5
    assert [k.model_dump() for k in token.kanji] == [{"character": "食", "jlpt": 5, "known": False}]


# --- the furigana rule, wired into analyze() -------------------------------


def test_known_vocabulary_overrides_furigana_even_if_the_rule_would_otherwise_trigger() -> None:
    """せんせい composes fine from 先/生's own on'yomi, so this specifically
    needs the kanji left *unknown* to prove the override is the vocabulary
    match, not the composed check."""
    known = KnownSet(vocabulary={"先生": frozenset({"せんせい"})})

    result = analyze("先生", known, {})

    [token] = result.paragraphs[0].tokens
    assert token.known_word is True
    assert token.needs_furigana is False


def test_unknown_kanji_needs_furigana() -> None:
    known = KnownSet(kanji={"一": frozenset({"いち"})})  # 緒 missing entirely

    result = analyze("一緒", known, {})

    [token] = result.paragraphs[0].tokens
    assert token.needs_furigana is True


def test_irregular_reading_needs_furigana_even_with_known_kanji() -> None:
    known = KnownSet(kanji={"今": frozenset({"こん", "いま"}), "日": frozenset({"にち", "ひ"})})

    result = analyze("今日", known, {})

    [token] = result.paragraphs[0].tokens
    assert token.needs_furigana is True


def test_composed_reading_with_known_kanji_does_not_need_furigana() -> None:
    known = KnownSet(kanji={"学": frozenset({"がく"}), "生": frozenset({"せい"})})

    result = analyze("学生", known, {})

    [token] = result.paragraphs[0].tokens
    assert token.needs_furigana is False


def test_kana_only_word_never_needs_furigana() -> None:
    known = KnownSet()

    result = analyze("ありがとう", known, {})

    [token] = result.paragraphs[0].tokens
    assert token.needs_furigana is False


# --- collect_lemmas ---------------------------------------------------------


def test_collect_lemmas_is_distinct_and_tokenizer_derived() -> None:
    keys = collect_lemmas("日の日")

    assert keys.count(("日", "ひ")) == 1
    assert ("の", "の") in keys


def test_collect_lemmas_includes_both_candidates_for_a_fallback_prone_word() -> None:
    """撮っ needs both (撮る, とる) and (取る, とる) batched -- see
    `lookup_candidates` -- since only the caller holding the batch result
    can tell, after the fact, whether the primary candidate was enough."""
    keys = collect_lemmas("撮って")

    assert ("撮る", "とる") in keys
    assert ("取る", "とる") in keys


# --- lookup_candidates -------------------------------------------------------


def test_lookup_candidates_is_just_the_primary_form_when_unidic_agrees() -> None:
    [token] = tokenize_paragraph("日")
    assert lookup_candidates(token) == [("日", "ひ")]


def test_lookup_candidates_adds_the_fallback_only_when_it_differs() -> None:
    [token] = tokenize_paragraph("撮っ")
    assert lookup_candidates(token) == [("撮る", "とる"), ("取る", "とる")]


# --- JLPT / known-vocabulary fall back from the written base form to -------
# --- unidic's own lemma, never the other way around ------------------------


def test_jlpt_prefers_the_primary_candidate_over_the_fallback() -> None:
    """撮る (the correct word) is in the lookup at N3; 取る (unidic's wrong
    headword for this surface) must not override it even if it is also
    present, e.g. at a different level, for the unrelated word 取る itself."""
    known = KnownSet()
    jlpt_lookup = {
        ("撮る", "とる"): _jlpt("撮る", "とる", 3, {"撮": 3}),
        ("取る", "とる"): _jlpt("取る", "とる", 5, {"取": 5}),
    }

    result = analyze("撮って", known, jlpt_lookup)

    token = next(t for t in result.paragraphs[0].tokens if t.surface == "撮っ")
    assert token.jlpt == 3
    assert [k.model_dump() for k in token.kanji] == [{"character": "撮", "jlpt": 3, "known": False}]


def test_jlpt_falls_back_to_the_alternate_lemma_when_the_base_form_is_unlisted() -> None:
    """いる's own base form has no kanji breakdown to speak of; falling
    back to unidic's 居る must not invent a kanji occurrence where the
    surface (い) has none -- `token.kanji` stays empty regardless."""
    known = KnownSet()
    jlpt_lookup = {("居る", "いる"): _jlpt("居る", "いる", 5, {"居": 5})}

    result = analyze("いました", known, jlpt_lookup)

    token = result.paragraphs[0].tokens[0]
    assert token.surface == "い"
    assert token.jlpt == 5
    assert token.kanji == []


def test_jlpt_is_null_when_neither_candidate_is_in_the_lookup() -> None:
    known = KnownSet()

    result = analyze("撮って", known, {})

    token = next(t for t in result.paragraphs[0].tokens if t.surface == "撮っ")
    assert token.jlpt is None


def test_known_vocabulary_matches_via_the_fallback_lemma() -> None:
    """こと's base form has no kanji of its own -- a learner's known
    vocabulary list, keyed by the word's dictionary headword, would know it
    as 事, not こと."""
    known = KnownSet(vocabulary={"事": frozenset({"こと"})})

    result = analyze("ことができました", known, {})

    token = next(t for t in result.paragraphs[0].tokens if t.surface == "こと")
    assert token.known_word is True
