"""`analyze()`: text + known set + JLPT lookup -> `TextAnalysis` (issue #7).

Pure and synchronous on purpose -- #8 measures a generated text with it and
#9 renders its tokens, and neither should need a live MCP connection (or
even `pytest-asyncio`) to exercise it. Everything that talks to the network
lives one layer up, in `app/api/analysis.py`'s route handler: it fetches the
known set (`known_set.fetch_known_set`) and batches `get_jlpt_levels` over
this module's own tokenizer output, then calls `analyze()` with the results.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from . import kanji_trainer as kt
from .furigana import (
    RawToken,
    _is_kana,
    _is_kanji,
    is_reading_composed,
    split_paragraphs,
    tokenize_paragraph,
)
from .known_set import KnownSet
from .models import JlptMix, KanjiInfo, Metrics, Paragraph, RubySegment, TextAnalysis, Token


def _kanji_characters(text: str) -> list[str]:
    """Every kanji character in `text`, in order, repeats included -- a
    token's own `kanji` list, and what `kanji_total`/`kanji_unknown` count.

    Deliberately narrower than `furigana._is_kanji` (which also treats 々/〆
    as "non-kana" so the ruby splitter puts them in a kanji run): neither is
    ever a Kanji Trainer subject of its own, so counting one as a kanji
    occurrence would always show up as "unknown" -- not a kanji the learner
    could ever know, since there is nothing to know.
    """
    return [char for char in text if "一" <= char <= "鿿" or "㐀" <= char <= "䶿"]


def _is_countable_character(char: str) -> bool:
    """Kana, kanji, or a latin letter/digit (full-width included) -- what
    `Metrics.characters` counts. Punctuation and whitespace are not."""
    if char.isspace():
        return False
    if _is_kana(char) or _is_kanji(char):
        return True
    return char.isalnum()


def _jlpt_key(lemma: str, reading: str) -> tuple[str, str | None]:
    """The key both `collect_lemmas()` and `_build_token()` use to look a
    token up in a `jlpt_lookup` mapping -- a missing reading is `None`
    rather than `""`, matching `kanji_trainer.JlptQuery`'s own convention
    (no reading narrows nothing, rather than matching only an empty one).
    """
    return (lemma, reading or None)


def lookup_candidates(raw: RawToken) -> list[tuple[str, str]]:
    """Written-form candidates to look `raw` up by in an external word list
    keyed by written form + reading -- JLPT levels, the JMdict dictionary,
    and the known-vocabulary match all use this same order, so none of them
    duplicates it:

    1. `(raw.lemma, raw.lemma_reading)` -- the word's own base form
       (unidic's `orthBase`) with its own reading (`kanaBase`), e.g.
       (行く, いく) for the surface 行き, or (撮る, とる) for 撮っ.
    2. `(raw.alt_lemma, raw.lemma_reading)`, only when `raw.alt_lemma` is
       set (unidic's own `lemma` feature named a different written form --
       see `furigana._base_form`'s doc comment) -- e.g. (事, こと) for the
       kana-written surface こと, whose own base form has no kanji to look
       a kanji-keyed list entry up by at all.

    A caller tries candidate 1 first and falls back to candidate 2 only on
    a miss -- never the other way around, since candidate 2 can name the
    *wrong word* for a surface like 撮っ (base form 撮る, but unidic's own
    `lemma` there is 取る, "to take", a different verb that merely shares a
    reading).
    """
    candidates = [(raw.lemma, raw.lemma_reading)]
    if raw.alt_lemma and raw.alt_lemma != raw.lemma:
        candidates.append((raw.alt_lemma, raw.lemma_reading))
    return candidates


def collect_lemmas(text: str) -> list[tuple[str, str | None]]:
    """Every distinct `(lemma, reading)` pair `analyze()` would look up for
    `text` -- both `lookup_candidates()` entries for every token, not just
    the preferred one, since a caller batching `get_jlpt_levels` has no
    other chance to ask for the fallback candidate too (see the module
    docstring, and `app/api/analysis.py`).

    Tokenises `text` itself rather than re-deriving it from a prior
    `analyze()` call's tokens, so a caller never has to run the tokenizer by
    hand to find out what to batch.
    """
    keys: dict[tuple[str, str | None], None] = {}
    for paragraph_text in split_paragraphs(text):
        for raw in tokenize_paragraph(paragraph_text):
            for lemma, reading in lookup_candidates(raw):
                if lemma:
                    keys[_jlpt_key(lemma, reading)] = None
    return list(keys)


def _build_token(
    token_id: str,
    raw: RawToken,
    known: KnownSet,
    jlpt_lookup: Mapping[tuple[str, str | None], kt.JlptLevelResult],
) -> Token:
    kanji_chars = _kanji_characters(raw.lemma)
    candidates = lookup_candidates(raw)

    # The per-kanji breakdown always comes from the *primary* candidate's
    # own result, never the fallback's: `kanji_chars` is extracted from
    # `raw.lemma`, which is exactly the text the primary candidate queried
    # JLPT with, so its own `kanji` list lines up with `kanji_chars`
    # character for character. The fallback candidate's text (e.g. 事 for
    # こと) would not -- but every real case where the fallback actually
    # wins is one where the primary (base) form has no kanji at all (いる,
    # する, ある, ない, くれる, できる, こと -- see `furigana._base_form`),
    # so `kanji_chars` is empty there and the question does not arise.
    primary_result = jlpt_lookup.get(_jlpt_key(*candidates[0]))

    # Only a word (`is_word`) has a JLPT level of its own: a particle never
    # did, and neither does a verb that `_mark_compound_particles` has just
    # folded into a fixed grammaticalised particle (について, に対して, ...
    # -- see CLAUDE.md "Text analysis") -- its kanji still get a per-
    # character level below (`kanji_info`, unrelated to `token.jlpt`, and
    # still wanted for the furigana rule and the unknown-kanji share), but
    # the token itself is grammar now, not a vocabulary item with a level.
    word_jlpt: int | None = None
    if raw.is_word:
        word_jlpt = primary_result.jlpt if primary_result is not None else None
        if word_jlpt is None:
            for lemma, reading in candidates[1:]:
                fallback_result = jlpt_lookup.get(_jlpt_key(lemma, reading))
                if fallback_result is not None and fallback_result.jlpt is not None:
                    word_jlpt = fallback_result.jlpt
                    break

    kanji_jlpt: dict[str, int | None] = {}
    if primary_result is not None:
        for kanji_level in primary_result.kanji:
            kanji_jlpt.setdefault(kanji_level.character, kanji_level.jlpt)

    kanji_info = [
        KanjiInfo(character=char, jlpt=kanji_jlpt.get(char), known=known.knows_kanji(char))
        for char in kanji_chars
    ]

    known_word = any(known.knows_word(lemma, reading) for lemma, reading in candidates)

    # No kanji, a known vocabulary match, or no reading at all (nothing to
    # put furigana on, or to test composition with) -- needs_furigana stays
    # False in every one of those cases. This check is about the *surface*
    # (raw.reading, not raw.lemma_reading) -- it is asking whether the word
    # as actually written needs a ruby reading, which is unrelated to which
    # base form found it in a word list.
    needs_furigana = False
    if kanji_chars and not known_word and raw.reading:
        any_unknown = any(not info.known for info in kanji_info)
        composed = is_reading_composed(raw.surface, raw.reading, known.kanji)
        needs_furigana = any_unknown or not composed

    return Token(
        id=token_id,
        surface=raw.surface,
        lemma=raw.lemma,
        reading=raw.reading,
        lemma_reading=raw.lemma_reading,
        pos=raw.pos,
        segments=raw.segments or [RubySegment(base=raw.surface)],
        jlpt=word_jlpt,
        kanji=kanji_info,
        known_word=known_word,
        needs_furigana=needs_furigana,
        is_word=raw.is_word,
    )


@dataclass(frozen=True)
class _CompoundParticlePattern:
    """One of the fixed 複合助詞 (compound particle) sequences documented in
    CLAUDE.md "Text analysis" -- a case particle followed by a verb's
    connective form, matched by that verb's own `lemma` (unidic's
    `orthBase`, never its `lemma` feature -- see `furigana._base_form`) so
    a grammaticalised use is told apart from an unrelated content verb that
    merely shares a reading: によって's よる is never confused with 寄る
    ("stop by"), and において's おく must stay the classical (kana) "に於く"
    and never 置く ("to place", kanji) -- see `tokenize_paragraph`'s own
    orthBase handling, which already keeps those apart the same way it
    keeps 着く/就く apart from つく (handled separately below,
    `_tsuku_span`, since its kana/kanji split alone is not enough -- see
    that function's docstring).
    """

    particle: str
    lemma: str
    #: True when the particle's own bare 連用形 (対し, とり, とし, おき, ...)
    #: is never the grammaticalised use on its own -- にとって and におい
    #: て are always complete with て; the others (に対して/対し, によって/
    #: により, として/とし, に関して/関し, をめぐって/めぐり, に基づいて/
    #: 基づき, に向けて/向け, に従って/従い) also show up in formal/news
    #: register without it (NHK headlines favour the bare form), and a
    #: bare match is excluded instead by `_bare_form_is_finite`.
    requires_te: bool
    #: Lemmas that, found right after a *consumed* て/で, mean this was a
    #: literal verb + auxiliary chain rather than the particle -- 友人に
    #: とってもらった (literal とる, "take", + the benefactive もらう) and
    #: 母にとっておいた (+ おく) read identically to にとって up to that
    #: point; see `_tsuku_span` for について's own version of this
    #: (犬が私についてきた/ていった -- the lexicalised ついてくる/いく).
    aux_after_te: frozenset[str] = frozenset()
    #: として only: と's *other* common job is the quotative/volitional
    #: "〜(よ)うとした/として" ("tried to ..."), which always has a verb
    #: right before と (逃げようとして) where として has a noun/pronoun/
    #: suffix instead (学生として, 委員長として) -- see `_compound_span`.
    forbid_preceding_verb: bool = False


_COMPOUND_PATTERNS: dict[tuple[str, str], _CompoundParticlePattern] = {
    (p.particle, p.lemma): p
    for p in (
        _CompoundParticlePattern("に", "対する", requires_te=False),
        _CompoundParticlePattern("に", "よる", requires_te=False),
        _CompoundParticlePattern("と", "する", requires_te=False, forbid_preceding_verb=True),
        _CompoundParticlePattern(
            "に", "とる", requires_te=True,
            aux_after_te=frozenset({"もらう", "くれる", "あげる", "やる", "おく", "しまう"}),
        ),
        _CompoundParticlePattern("に", "関する", requires_te=False),
        _CompoundParticlePattern("に", "おく", requires_te=True),
        _CompoundParticlePattern("を", "めぐる", requires_te=False),
        _CompoundParticlePattern("に", "基づく", requires_te=False),
        _CompoundParticlePattern("に", "向ける", requires_te=False),
        _CompoundParticlePattern("に", "従う", requires_te=False),
    )
}  # fmt: skip

_TE_SURFACES = ("て", "で")
_TSUKU_AUX_AFTER_TE = frozenset({"くる", "いく"})


def _consumes_te(tokens: list[RawToken], index: int) -> bool:
    return 0 <= index < len(tokens) and tokens[index].pos == "助詞" and tokens[index].surface in _TE_SURFACES


def _bare_form_is_finite(tokens: list[RawToken], index: int) -> bool:
    """True when `tokens[index]` exists and is a 助動詞 (た/だ/ます/ない/...)
    completing the *previous* token's own conjugation, rather than a comma,
    a particle, a new clause, or the paragraph ending -- the signal that a
    bare 連用形 (対し, とし, 向け, ...) is that verb's own finite predicate
    (対した, とした, 向けた are complete sentences on their own) and not a
    compound-particle connector introducing a separate one (対し、, とし、,
    向け、...). Checked only for the patterns above whose `requires_te` is
    False -- a verb that already took て/で is unambiguously non-finite."""
    return 0 <= index < len(tokens) and tokens[index].pos == "助動詞"


def _tsuku_span(tokens: list[RawToken], index: int) -> int | None:
    """について/につき: つく's kana/kanji orthBase split (`tokenize_paragraph`)
    already keeps the grammaticalised use apart from 着く ("arrive"),
    就く ("take up a post") and 置く ("place") -- but kana つく alone still
    covers three different things: について/につき themselves, the literal
    "stick to" sense with no connecting て at all (手についた, インクが手に
    ついた), and the lexicalised "follow along" compound verbs ついてくる/
    ついていく (犬が私についてきた, 彼のあとをついていった). The first of
    those is excluded by requiring て whenever the surface is the onbin
    stem つい (unlike につき's bare 連用形 つき, つい never stands on its
    own); the third by refusing one when the token right after て is くる/
    いく. A plain verb continuing a coordinated clause right after について
    (犬が私について歩いた, "walked, following me") is not caught by this --
    see CLAUDE.md and the report for that acknowledged gap."""
    body = tokens[index + 1]
    if body.surface == "つき":
        return None if _bare_form_is_finite(tokens, index + 2) else 2
    if body.surface == "つい" and _consumes_te(tokens, index + 2):
        if index + 3 < len(tokens) and tokens[index + 3].lemma in _TSUKU_AUX_AFTER_TE:
            return None
        return 3
    return None


def _tomoni_span(tokens: list[RawToken], index: int) -> int | None:
    """とともに/と共に: と + とも/共 (名詞, lemma とも or 共 -- 共に written
    with the kanji tokenises the same way, see CLAUDE.md) + に. Unlike the
    other patterns the body is not a verb at all, so this never overlaps
    with `_COMPOUND_PATTERNS`. The leading と is what keeps this apart from
    とも used as "friend" (友とともだちと -- never directly preceded by its
    own と) or as the concessive/contrastive とも (貧しくとも, それとも,
    二人とも -- each already its own single 助詞 token, or split ど+も,
    never a 名詞 preceded by と)."""
    particle, body = tokens[index], tokens[index + 1]
    if (
        particle.surface == "と"
        and body.pos == "名詞"
        and body.lemma in ("とも", "共")
        and index + 2 < len(tokens)
        and tokens[index + 2].pos == "助詞"
        and tokens[index + 2].surface == "に"
    ):
        return 3
    return None


def _compound_span(tokens: list[RawToken], index: int) -> int | None:
    """How many tokens starting at `index` form one fixed compound particle
    (2 or 3), or None when none of them start here -- see
    `_mark_compound_particles`."""
    particle, body = tokens[index], tokens[index + 1]
    if particle.surface == "に" and body.lemma == "つく" and body.pos == "動詞":
        return _tsuku_span(tokens, index)
    if body.pos != "動詞":
        return _tomoni_span(tokens, index)

    pattern = _COMPOUND_PATTERNS.get((particle.surface, body.lemma))
    if pattern is None:
        return None
    if pattern.forbid_preceding_verb and index > 0 and tokens[index - 1].pos == "動詞":
        return None

    if _consumes_te(tokens, index + 2):
        if index + 3 < len(tokens) and tokens[index + 3].lemma in pattern.aux_after_te:
            return None
        return 3
    if pattern.requires_te or _bare_form_is_finite(tokens, index + 2):
        return None
    return 2


def _mark_compound_particles(tokens: list[RawToken]) -> None:
    """Fold every fixed 複合助詞 sequence in `tokens` into grammar, in
    place: について, に対して/対し, によって/により, として/とし, にとって,
    に関して/関し, において, につき, をめぐって/めぐり, に基づいて/基づき,
    に向けて/向け, とともに/と共に, に従って/従い -- see CLAUDE.md "Text
    analysis" for the full rule and the false positives it is tested
    against. Runs once per paragraph, straight after `tokenize_paragraph`,
    before `_build_token` turns any of it into a `Token` -- a token marked
    `is_word = False` here is indistinguishable downstream from an ordinary
    particle: no JLPT (`_build_token`), no word count, no JLPT mix
    (`_compute_metrics`/`_jlpt_mix`, both keyed on `is_word`), no peek (the
    frontend). Its kanji keep counting toward the unknown-kanji share and
    keep getting furigana when unknown regardless -- `_build_token` reads
    those straight off `raw.lemma`/`raw.surface`, never off `is_word`.
    """
    index = 0
    while index < len(tokens):
        if tokens[index].pos != "助詞" or index + 1 >= len(tokens):
            index += 1
            continue
        span = _compound_span(tokens, index)
        if span is None:
            index += 1
            continue
        for token in tokens[index : index + span]:
            token.is_word = False
        index += span


def _jlpt_mix(content_tokens: list[Token]) -> JlptMix:
    if not content_tokens:
        return JlptMix()
    buckets = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0, None: 0}
    for token in content_tokens:
        level = token.jlpt if token.jlpt in buckets else None
        buckets[level] += 1
    total = len(content_tokens)
    return JlptMix(
        n5=buckets[5] / total,
        n4=buckets[4] / total,
        n3=buckets[3] / total,
        n2=buckets[2] / total,
        n1=buckets[1] / total,
        unlisted=buckets[None] / total,
    )


def _compute_metrics(text: str, paragraphs: list[Paragraph]) -> Metrics:
    characters = sum(1 for char in text if _is_countable_character(char))
    all_tokens = [token for paragraph in paragraphs for token in paragraph.tokens]
    content_tokens = [token for token in all_tokens if token.is_word]

    kanji_total = sum(len(token.kanji) for token in all_tokens)
    kanji_unknown = sum(1 for token in all_tokens for kanji in token.kanji if not kanji.known)
    unknown_kanji_share = kanji_unknown / kanji_total if kanji_total else 0.0

    return Metrics(
        characters=characters,
        words=len(content_tokens),
        kanji_total=kanji_total,
        kanji_unknown=kanji_unknown,
        unknown_kanji_share=unknown_kanji_share,
        jlpt_mix=_jlpt_mix(content_tokens),
    )


def analyze(
    text: str,
    known: KnownSet,
    jlpt_lookup: Mapping[tuple[str, str | None], kt.JlptLevelResult],
) -> TextAnalysis:
    """Turn `text` into tokens and metrics -- pure, synchronous, no MCP.

    `known` is a plain `KnownSet` (see `known_set.py`); `jlpt_lookup` maps
    `(lemma, reading or None)` (see `_jlpt_key`) to the `JlptLevelResult`
    `kanji_trainer.get_jlpt_levels` would return for that pair -- the caller
    batches that call once, over `collect_lemmas(text)`, rather than this
    function reaching out itself.
    """
    paragraphs: list[Paragraph] = []
    for paragraph_index, paragraph_text in enumerate(split_paragraphs(text)):
        raw_tokens = tokenize_paragraph(paragraph_text)
        _mark_compound_particles(raw_tokens)
        tokens = [
            _build_token(f"{paragraph_index}-{token_index}", raw, known, jlpt_lookup)
            for token_index, raw in enumerate(raw_tokens)
        ]
        paragraphs.append(Paragraph(tokens=tokens))

    return TextAnalysis(paragraphs=paragraphs, metrics=_compute_metrics(text, paragraphs))
