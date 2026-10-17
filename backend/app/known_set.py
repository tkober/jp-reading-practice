"""`KnownSet`: the learner's known kanji/vocabulary, as a plain argument.

`analysis.py`'s `analyze()` has to be pure and testable without MCP (issue
#7's whole point -- #8 measures a generated text with it, #9 renders its
tokens, and neither should need a live Kanji Trainer to run their own
tests). This module is the seam: `build_known_set()` turns
`kanji_trainer.py`'s `KnownItem` lists into the small lookup structure
`analyze()` actually needs, and `fetch_known_set()` is the thin async
wrapper that calls the MCP client -- the only part of this file that is not
pure.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import kanji_trainer as kt
from .furigana import to_hiragana

#: WaniKani's own reading `type` values (see kanji_trainer.ReadingOut) --
#: `nanori` (name readings) are deliberately excluded from a kanji's known
#: *readings*: they are not used to compose ordinary vocabulary readings, so
#: including them would let obscure name readings pass the furigana rule's
#: "composed from known readings" check for everyday words.
_ONYOMI = "onyomi"
_KUNYOMI = "kunyomi"


class KnownSet(BaseModel):
    """What the learner already knows, as kanji_trainer.py's own `KnownItem`
    lists reduced to exactly what `analyze()` needs.

    `kanji` maps a character to its known *readings* (hiragana, on'yomi
    folded, kun'yomi already bare of okurigana -- see
    `_kanji_known_readings`): used by `furigana.is_reading_composed` to
    decide whether a word's reading follows from its kanji, and by
    `knows_kanji` to decide whether a kanji is known at all.

    `vocabulary` maps a word's dictionary form (its JMdict/kanji-trainer
    "characters", or -- for a kana-only word, which kanji-trainer's own
    `characters` is `None` for -- one of its readings standing in for it) to
    every reading the learner knows it under.
    """

    kanji: dict[str, frozenset[str]] = Field(default_factory=dict)
    vocabulary: dict[str, frozenset[str]] = Field(default_factory=dict)

    def knows_kanji(self, character: str) -> bool:
        return character in self.kanji

    def knows_word(self, text: str, reading: str) -> bool:
        return reading in self.vocabulary.get(text, frozenset())


def _kanji_known_readings(item: kt.KnownItem) -> frozenset[str]:
    """A kanji's known readings, folded for `is_reading_composed`.

    On'yomi is folded to hiragana (kanji-trainer's WaniKani-sourced data
    already stores it that way, so this is a defensive no-op in practice,
    not a load-bearing conversion). Kun'yomi is taken bare of okurigana --
    again already true of kanji-trainer's own data (e.g. 飲's kun'yomi is
    stored as "の", not "のむ"; confirmed against a real import, see the
    issue #7 report), but a literal "." separator (the kanjidic/EDICT
    convention this app does not otherwise use) is stripped too, in case a
    future data source ever uses it.
    """
    readings: set[str] = set()
    for reading in item.readings:
        if reading.type == _ONYOMI:
            readings.add(to_hiragana(reading.reading))
        elif reading.type == _KUNYOMI:
            stem = reading.reading.split(".", 1)[0]
            readings.add(to_hiragana(stem))
        # Untyped (vocabulary readings never reach this function) and
        # `nanori` readings are not composition material -- see the module
        # docstring.
    return frozenset(readings)


def build_known_set(known_kanji: list[kt.KnownItem], known_vocabulary: list[kt.KnownItem]) -> KnownSet:
    """Pure: reduces two `KnownItem` lists to a `KnownSet`. Called from the
    async `fetch_known_set()` below, and directly from tests that want a
    `KnownSet` without any MCP involved at all.
    """
    kanji: dict[str, frozenset[str]] = {}
    for item in known_kanji:
        if item.object_type != "kanji" or not item.characters:
            continue
        kanji[item.characters] = _kanji_known_readings(item)

    vocabulary: dict[str, set[str]] = {}
    for item in known_vocabulary:
        readings = {to_hiragana(reading.reading) for reading in item.readings}
        if not readings:
            continue
        # kana_vocabulary has no `characters` of its own -- one of its own
        # readings stands in as the lookup key instead (see the class
        # doc comment), since `analyze()` matches by a token's lemma, and a
        # kana-only token's lemma is its reading.
        key = item.characters or next(iter(sorted(readings)))
        vocabulary.setdefault(key, set()).update(readings)

    return KnownSet(kanji=kanji, vocabulary={key: frozenset(value) for key, value in vocabulary.items()})


async def fetch_known_set(url: str) -> KnownSet:
    """The only non-pure part of this module: fetches both known-item lists
    from the Kanji Trainer and reduces them. Raises
    `kanji_trainer.KanjiTrainerUnavailable` exactly like the calls it wraps
    -- the caller (the `/api/analysis` route) decides how to degrade.
    """
    known_kanji = await kt.get_known_kanji(url)
    known_vocabulary = await kt.get_known_vocabulary(url)
    return build_known_set(known_kanji, known_vocabulary)
