"""Tokenisation and furigana for the text analysis (issue #7).

Ported from jp-conversation-practice's `backend/app/furigana.py`: the kana/
kanji classification, the hiragana fold, the ruby-only-over-kanji splitting
with its okurigana alignment and whole-word fallback, `_SURFACE_READINGS`,
and the graceful `None` when the dictionary cannot be loaded. That module
worked on a whole transcript line and returned one flat list of ruby
segments; this one needs the morphemes themselves (lemma, reading, part of
speech) to build `Token`s and look up vocabulary/JLPT, so it tokenises first
and then runs the same splitting logic per word rather than per line.

Readings come from a morphological analysis (MeCab via fugashi, dictionary
unidic-lite) rather than a per-kanji table, for the same reason as there: a
kanji's reading depends on the word around it (今日 is キョウ, not イマヒ).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .models import RubySegment

logger = logging.getLogger(__name__)

# Katakana and hiragana sit 0x60 apart in Unicode, which is what makes a
# reading (katakana) comparable to the okurigana in a surface (hiragana).
_KANA_DISTANCE = 0x60

_KANA_MARKS = "ーゝゞヽヾ"

# Where unidic's reading is defensible but not what a learner is taught: the
# pronoun 私 is ワタクシ in the dictionary and わたし in every textbook. Keyed
# by the whole surface, so 私立 (シリツ) is unaffected.
_SURFACE_READINGS = {"私": "わたし"}

# Inflectable parts of speech, where unidic's own `lemma` feature is the
# dictionary form we want for vocabulary/JLPT lookups (食べた -> 食べる).
# Every other part of speech keeps its surface as its own lemma instead --
# nouns do not conjugate in Japanese, so unidic's `lemma` for one is either
# the surface again or, for many proper nouns (see `_lemma_for`'s doc
# comment), its katakana pronunciation, which would send the wrong string to
# both vocabulary matching and the Kanji Trainer's JLPT lookup.
_INFLECTABLE_POS1 = {"動詞", "形容詞", "形状詞"}

# Excluded from `Token.is_word`: particles, auxiliary verbs and punctuation/
# symbols carry no vocabulary or JLPT level of their own. Numbers (名詞-数詞)
# are an ordinary 名詞 and are not excluded.
_EXCLUDED_POS1 = {"助詞", "助動詞", "補助記号", "空白"}


def _is_kana(char: str) -> bool:
    return "ぁ" <= char <= "ゖ" or "ァ" <= char <= "ヺ" or char in _KANA_MARKS


def _is_kanji(char: str) -> bool:
    # CJK unified ideographs and extension A, plus the repeat mark 々 and 〆.
    return "一" <= char <= "鿿" or "㐀" <= char <= "䶿" or char in "々〆"


def to_hiragana(text: str) -> str:
    return "".join(
        chr(ord(char) - _KANA_DISTANCE) if "ァ" <= char <= "ヶ" else char for char in text
    )


def _runs(surface: str) -> list[tuple[str, bool]]:
    """Split a surface into alternating kana / non-kana runs."""
    runs: list[tuple[str, bool]] = []
    for char in surface:
        kana = _is_kana(char)
        if runs and runs[-1][1] == kana:
            runs[-1] = (runs[-1][0] + char, kana)
        else:
            runs.append((char, kana))
    return runs


def _split_word(surface: str, reading: str) -> list[RubySegment]:
    """Distribute a word's reading over its kanji runs: 食べる -> 食[た]べる.

    The okurigana is already readable, so putting the whole reading over the
    whole word (食べる[たべる]) would bury the one part the learner needs.
    Each kana run in the surface has to appear verbatim in the reading; the
    reading between two of them belongs to the kanji run in between.

    Greedy left to right, and anything that does not line up falls back to
    one ruby over the whole word -- still correct, only less precise.
    """
    whole = [RubySegment(base=surface, reading=reading)]
    runs = _runs(surface)
    segments: list[RubySegment] = []
    position = 0

    for index, (run, is_kana) in enumerate(runs):
        if is_kana:
            expected = to_hiragana(run)
            if not reading.startswith(expected, position):
                return whole
            segments.append(RubySegment(base=run))
            position += len(expected)
            continue

        following = to_hiragana(runs[index + 1][0]) if index + 1 < len(runs) else ""
        if following:
            # +1: a kanji run reads as at least one kana, so an okurigana
            # match at the current position would be the wrong one.
            end = reading.find(following, position + 1)
        else:
            end = len(reading)
        if end <= position:
            return whole
        segments.append(RubySegment(base=run, reading=reading[position:end]))
        position = end

    if position != len(reading):
        return whole
    return segments


def _merge(segments: list[RubySegment]) -> list[RubySegment]:
    """Glue neighbouring plain segments together to keep the payload small."""
    merged: list[RubySegment] = []
    for segment in segments:
        if segment.reading is None and merged and merged[-1].reading is None:
            merged[-1] = RubySegment(base=merged[-1].base + segment.base)
        else:
            merged.append(segment)
    return merged


@lru_cache(maxsize=1)
def _tagger() -> Any | None:
    """The MeCab tagger, or None if it cannot be loaded.

    A missing or broken dictionary must not take the analysis down with it:
    without a tagger, `tokenize_paragraph` degrades to one opaque token per
    paragraph (see its doc comment), the same way jp-conversation-practice's
    `annotate()` degrades to plain text.
    """
    try:
        import fugashi

        return fugashi.Tagger()
    except Exception:  # pragma: no cover - depends on the deployed environment
        logger.warning("Tokenisation disabled: MeCab/unidic could not be loaded", exc_info=True)
        return None


def _segments_for_word(surface: str, reading: str) -> list[RubySegment]:
    if reading and any(_is_kanji(char) for char in surface):
        return _merge(_split_word(surface, reading))
    return [RubySegment(base=surface)]


def _lemma_for(surface: str, pos1: str, feature_lemma: str | None) -> str:
    """The dictionary form used for vocabulary/JLPT lookups.

    Only inflectable words (verbs, i-adjectives, na-adjectives) need
    unidic's own `lemma` feature; every other part of speech keeps its
    surface. Two things make that the right default rather than an
    approximation: nouns do not conjugate, and unidic's `lemma` for many
    proper nouns is their *katakana pronunciation* rather than the written
    form -- 金沢 (the fixture title's own first word) comes back as lemma
    "カナザワ", which would send the wrong string to both vocabulary
    matching and `get_jlpt_levels`.
    """
    if pos1 in _INFLECTABLE_POS1 and feature_lemma:
        return feature_lemma
    return surface


def _is_word(pos1: str, surface: str) -> bool:
    if pos1 in _EXCLUDED_POS1:
        return False
    return surface.strip() != ""


@dataclass
class RawToken:
    """One morpheme, before vocabulary/JLPT annotation (see `analysis.py`)."""

    surface: str
    lemma: str
    reading: str
    pos: str
    segments: list[RubySegment] = field(default_factory=list)
    is_word: bool = False


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


def split_paragraphs(text: str) -> list[str]:
    """Split a text into paragraphs on blank lines.

    A single line break within a paragraph is dropped rather than kept as a
    character of its own -- Japanese prose does not use spaces between
    words, so a paragraph that happens to arrive pre-wrapped (e.g. copied
    from a generated text) should read as one continuous line again, not
    gain a stray line-break token.
    """
    blocks = _PARAGRAPH_BREAK.split(text.strip())
    paragraphs = []
    for block in blocks:
        joined = "".join(line.strip() for line in block.splitlines())
        if joined:
            paragraphs.append(joined)
    return paragraphs


def tokenize_paragraph(text: str) -> list[RawToken]:
    """Tokenise one paragraph (no blank lines) into `RawToken`s.

    Returns a single, non-word, plain-text token for the whole paragraph
    when the tagger could not be loaded -- the UI then shows the paragraph
    without any furigana or per-word interaction, the same degradation
    `annotate()` falls back to in jp-conversation-practice.
    """
    if not text:
        return []

    tagger = _tagger()
    if tagger is None:
        return [
            RawToken(
                surface=text,
                lemma=text,
                reading="",
                pos="UNKNOWN",
                segments=[RubySegment(base=text)],
                is_word=False,
            )
        ]

    tokens: list[RawToken] = []
    for word in tagger(text):
        surface = word.surface
        if not surface:
            continue
        pos1 = getattr(word.feature, "pos1", None) or "UNKNOWN"
        feature_lemma = getattr(word.feature, "lemma", None)
        lemma = _lemma_for(surface, pos1, feature_lemma)
        reading = _SURFACE_READINGS.get(
            surface, to_hiragana(getattr(word.feature, "kana", None) or "")
        )
        tokens.append(
            RawToken(
                surface=surface,
                lemma=lemma,
                reading=reading,
                pos=pos1,
                segments=_segments_for_word(surface, reading),
                is_word=_is_word(pos1, surface),
            )
        )
    return tokens


# --- the furigana rule --------------------------------------------------

# Rendaku: the first mora of a non-initial kanji's reading may voice, か -> が
# and so on (手紙 て + かみ -> てがみ).
_RENDAKU = {
    "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
    "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
    "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
    "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
}  # fmt: skip

# Gemination: つ/ち/く/き at the end of a reading may double into っ when
# another kanji follows in the same run (学 がく + 校 こう -> がっこう).
_GEMINATABLE = "つちくき"


def _decompose_kanji_run(run: str, slice_: str, known_kanji: dict[str, frozenset[str]]) -> bool:
    """Can `slice_` be built by concatenating one known reading per kanji in
    `run`, in order, tolerating rendaku and gemination at the boundary
    between two kanji?
    """

    def candidates_for(position: int, run_index: int) -> list[str]:
        char = run[run_index]
        readings = known_kanji.get(char)
        if not readings:
            return []
        has_next = run_index + 1 < len(run)
        variants: set[str] = set()
        for reading in readings:
            variants.add(reading)
            if run_index > 0 and reading and reading[0] in _RENDAKU:
                variants.add(_RENDAKU[reading[0]] + reading[1:])
        if has_next:
            for variant in list(variants):
                if variant and variant[-1] in _GEMINATABLE:
                    variants.add(variant[:-1] + "っ")
        return list(variants)

    def search(run_index: int, position: int) -> bool:
        if run_index == len(run):
            return position == len(slice_)
        for variant in candidates_for(position, run_index):
            if variant and slice_.startswith(variant, position):
                if search(run_index + 1, position + len(variant)):
                    return True
        return False

    return search(0, 0)


def is_reading_composed(surface: str, reading: str, known_kanji: dict[str, frozenset[str]]) -> bool:
    """Can `reading` be assembled from `surface`'s own kanji, each matching
    one of its *known* readings, plus the surface's own okurigana verbatim?

    This is the second half of the furigana rule (see `needs_furigana`): a
    word whose kanji are individually known can still read in a way that
    does not follow from them (今日 read きょう, not from 今/日's own
    readings) and must keep its furigana regardless.

    The algorithm walks `surface`'s kana/non-kana runs left to right (same
    split as `_split_word`'s ruby placement): a kana run must appear
    verbatim in `reading` at the current position (this is what makes
    okurigana alignment part of the check -- 飲み物's み has to show up
    between 飲 and 物's own readings); a kanji run's corresponding slice of
    `reading` is found the same way `_split_word` finds it (up to the next
    kana run, or the end), and then has to decompose into `known_kanji`'s
    readings for that run's characters, one per character, tolerating
    rendaku and gemination at the boundary between two of them.

    `known_kanji` maps a character to its known readings, already folded to
    hiragana and (per kanji-trainer's own data) already bare of okurigana --
    see `known_set.py`'s `_kanji_known_readings`. A kanji missing from
    `known_kanji` (i.e. not known at all) simply has no candidates, so a run
    containing one can never decompose -- which is also why `needs_furigana`
    only has to ask this one question rather than this and "is every kanji
    known" separately.
    """
    if not reading:
        return False

    runs = _runs(surface)
    position = 0
    for index, (run, is_kana) in enumerate(runs):
        if is_kana:
            expected = to_hiragana(run)
            if not reading.startswith(expected, position):
                return False
            position += len(expected)
            continue

        if any(not _is_kanji(char) for char in run):
            # A non-kana, non-kanji run (punctuation, latin, digits) has no
            # per-character reading to decompose -- be conservative.
            return False

        following = to_hiragana(runs[index + 1][0]) if index + 1 < len(runs) else ""
        end = reading.find(following, position + 1) if following else len(reading)
        if end <= position:
            return False
        if not _decompose_kanji_run(run, reading[position:end], known_kanji):
            return False
        position = end

    return position == len(reading)
