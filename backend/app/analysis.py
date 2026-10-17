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


def collect_lemmas(text: str) -> list[tuple[str, str | None]]:
    """Every distinct `(lemma, reading)` pair `analyze()` would look up for
    `text`, for the caller to batch into one `get_jlpt_levels` call (see the
    module docstring, and `app/api/analysis.py`).

    Tokenises `text` itself rather than re-deriving it from a prior
    `analyze()` call's tokens, so a caller never has to run the tokenizer by
    hand to find out what to batch.
    """
    keys: dict[tuple[str, str | None], None] = {}
    for paragraph_text in split_paragraphs(text):
        for raw in tokenize_paragraph(paragraph_text):
            if raw.lemma:
                keys[_jlpt_key(raw.lemma, raw.reading)] = None
    return list(keys)


def _build_token(
    token_id: str,
    raw: RawToken,
    known: KnownSet,
    jlpt_lookup: Mapping[tuple[str, str | None], kt.JlptLevelResult],
) -> Token:
    kanji_chars = _kanji_characters(raw.lemma)
    jlpt_result = jlpt_lookup.get(_jlpt_key(raw.lemma, raw.reading))
    word_jlpt = jlpt_result.jlpt if jlpt_result is not None else None

    kanji_jlpt: dict[str, int | None] = {}
    if jlpt_result is not None:
        for kanji_level in jlpt_result.kanji:
            kanji_jlpt.setdefault(kanji_level.character, kanji_level.jlpt)

    kanji_info = [
        KanjiInfo(character=char, jlpt=kanji_jlpt.get(char), known=known.knows_kanji(char))
        for char in kanji_chars
    ]

    known_word = known.knows_word(raw.lemma, raw.reading)

    # No kanji, a known vocabulary match, or no reading at all (nothing to
    # put furigana on, or to test composition with) -- needs_furigana stays
    # False in every one of those cases.
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
