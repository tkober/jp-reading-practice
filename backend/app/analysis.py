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
        pos=raw.pos,
        segments=raw.segments or [RubySegment(base=raw.surface)],
        jlpt=word_jlpt,
        kanji=kanji_info,
        known_word=known_word,
        needs_furigana=needs_furigana,
        is_word=raw.is_word,
    )


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
        tokens = [
            _build_token(f"{paragraph_index}-{token_index}", raw, known, jlpt_lookup)
            for token_index, raw in enumerate(tokenize_paragraph(paragraph_text))
        ]
        paragraphs.append(Paragraph(tokens=tokens))

    return TextAnalysis(paragraphs=paragraphs, metrics=_compute_metrics(text, paragraphs))
