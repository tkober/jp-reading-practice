"""`analyze()` -- pure, no MCP (issue #7). Metrics, JLPT mix, and the
furigana rule wired into actual tokens (the rule itself has its own, much
larger test file, `test_furigana.py`)."""

from __future__ import annotations

import pytest

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


# --- compound particles (複合助詞) -----------------------------------------
# unidic splits these into their parts, so the verb inside would otherwise
# count as a content word on its own (について -> に/つい(つく)/て). See
# CLAUDE.md "Text analysis" for the full list and the false positives below.


def _token(text: str, surface: str) -> object:
    result = analyze(text, KnownSet(), {})
    tokens = result.paragraphs[0].tokens
    return next(t for t in tokens if t.surface == surface)


@pytest.mark.parametrize(
    ("text", "body_surface"),
    [
        ("日本の経済について話した。", "つい"),
        ("この件につき連絡します。", "つき"),
        ("この問題に対して検討する。", "対し"),
        ("この問題に対し、検討する。", "対し"),
        ("彼の努力によって成功した。", "よっ"),
        ("調査結果により判明した。", "より"),
        ("学生として勉強する。", "し"),
        ("委員長とし、会議を進めた。", "し"),
        ("先生にとって大切なことだ。", "とっ"),
        ("環境問題に関して議論した。", "関し"),
        ("環境問題に関し、議論が続く。", "関し"),
        ("東京において開催された。", "おい"),
        ("領土をめぐって対立した。", "めぐっ"),
        ("問題をめぐり議論が続いた。", "めぐり"),
        ("規則に基づいて行動する。", "基づい"),
        ("規則に基づき、行動する。", "基づき"),
        ("未来に向けて進む。", "向け"),
        ("将来に向け、準備を進める。", "向け"),
        ("家族とともに過ごす。", "とも"),
        ("家族と共に暮らす。", "共"),
        ("指示に従って動く。", "従っ"),
        ("指示に従い、動いた。", "従い"),
    ],
)
def test_compound_particle_verb_becomes_grammar(text: str, body_surface: str) -> None:
    token = _token(text, body_surface)
    assert token.is_word is False


@pytest.mark.parametrize(
    ("text", "body_surface"),
    [
        # について vs 着く/就く (arrive/take up a post -- different lemma)
        ("日本に着いて嬉しい。", "着い"),
        ("新しい地位に就いて喜んだ。", "就い"),
        # につき/について vs the literal "stick to" sense -- same lemma
        # (つく), but never on its own (手についた) or with a continuing
        # motion verb instead of a new clause (犬が私についてきた/
        # 彼のあとをついていった, the lexicalised ついてくる/いく)
        ("インクが手についた。", "つい"),
        ("犬が私についてきた。", "つい"),
        ("彼のあとをついていった。", "つい"),
        # について vs the literal "place" sense (置く, different lemma from
        # classical おく) -- 置く also keeps its own で-form "~ておく" aux
        # out of the picture, since that never follows に directly
        ("箱に置いて出かけた。", "置い"),
        ("テーブルに置いておいた。", "置い"),
        # 席に着く -- not even followed by て, nowhere close to a match
        ("席に着く。", "着く"),
        # によって vs 寄る ("stop by" -- different lemma from 因る/依る)
        ("店に寄ってパンを買った。", "寄っ"),
        # にとって vs the literal "take" sense -- same lemma (とる), but
        # chained onto a benefactive/aspectual auxiliary instead of
        # introducing a new clause (友人にとってもらった, 母にとっておいた)
        ("手に取って見る。", "取っ"),
        ("友人にとってもらった写真を見せた。", "とっ"),
        ("母にとっておいたケーキを食べた。", "とっ"),
        # として vs the quotative/volitional "〜(よ)うとした" ("tried to"),
        # which always has a verb (not a noun/pronoun) right before と
        ("彼は逃げようとして失敗した。", "し"),
        ("本を読もうとしたが時間がなかった。", "し"),
        # bare 連用形 as that verb's OWN finite predicate (対した, とした,
        # 向けた are complete sentences), not a compound-particle connector
        ("彼はその困難に対した。", "対し"),
        ("彼を委員長とした。", "し"),
        ("彼は顔を声に向けた。", "向け"),
        # をめぐって vs the literal "go around" sense (巡る, different
        # lemma from めぐる)
        ("地球を巡って衛星が動く。", "巡っ"),
        # とともに vs とも meaning "friend" -- a real word, but never
        # directly preceded by its own と the way the grammaticalised use
        # always is (二人とも and それとも don't even reach this check:
        # unidic splits their と+も into two separate particle tokens, not
        # a 名詞 とも, so there is no body token to match against at all)
        ("彼は私のともだ。", "とも"),
    ],
)
def test_compound_particle_false_positive_pairs_stay_words(text: str, body_surface: str) -> None:
    token = _token(text, body_surface)
    assert token.is_word is True


def test_compound_particle_tokens_keep_their_boundaries() -> None:
    """is_word goes to False, but について is still three separate tokens
    (に/つい/て) -- the reading text renders tokens, and the frontend maps
    is_word=false to plain text, so merging would lose nothing it needs but
    would complicate every other lookup for no reason."""
    result = analyze("経済について話した。", KnownSet(), {})

    surfaces = [t.surface for t in result.paragraphs[0].tokens]
    assert surfaces == ["経済", "に", "つい", "て", "話し", "た", "。"]


def test_compound_particle_kanji_still_counts_and_gets_furigana() -> None:
    """対 is on the page either way -- について's own verb still contributes
    to the unknown-kanji share and still needs furigana when unknown, even
    though it is grammar now, not a vocabulary word (issue's point 1)."""
    known = KnownSet()  # 対 unknown
    result = analyze("この問題に対して検討する。", known, {})

    token = next(t for t in result.paragraphs[0].tokens if t.surface == "対し")
    assert token.is_word is False
    assert [k.character for k in token.kanji] == ["対"]
    assert token.kanji[0].known is False
    assert token.needs_furigana is True  # 対 unknown -> needs furigana regardless of is_word

    assert result.metrics.kanji_total == 5  # 問,題,対,検,討
    assert result.metrics.kanji_unknown == 5


def test_compound_particle_has_no_jlpt_even_when_the_lookup_has_one() -> None:
    """対する would otherwise be N2 vocabulary -- as grammar it must not
    carry a word-level JLPT at all, matching "no JLPT" in the issue."""
    known = KnownSet()
    jlpt_lookup = {("対する", "たいする"): _jlpt("対する", "たいする", 2, {"対": 2})}

    result = analyze("この問題に対して検討する。", known, jlpt_lookup)

    token = next(t for t in result.paragraphs[0].tokens if t.surface == "対し")
    assert token.jlpt is None


def test_compound_particle_does_not_count_toward_words_or_jlpt_mix() -> None:
    known = KnownSet()
    jlpt_lookup = {("問題", "もんだい"): _jlpt("問題", "もんだい", 4, {"問": 4, "題": 4})}

    result = analyze("この問題に対して検討する。", known, jlpt_lookup)

    # content words: この(連体詞), 問題, 検討, する -- not に/対し/て
    assert result.metrics.words == 4
    assert result.metrics.jlpt_mix.n4 == pytest.approx(1 / 4)


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
