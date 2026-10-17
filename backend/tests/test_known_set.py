"""`build_known_set` -- reducing kanji_trainer.py's `KnownItem` lists to the
small `KnownSet` `analyze()` takes. Reading values below mirror a real
kanji-trainer import inspected for issue #7 (kanji_trainer_t86, see the
report) rather than made up -- in particular that kun'yomi readings already
come back bare of okurigana (飲's kun'yomi is "の", not "のむ").
"""

from __future__ import annotations

from app import kanji_trainer as kt
from app.known_set import KnownSet, build_known_set


def _kanji(characters: str, *readings: tuple[str, str]) -> kt.KnownItem:
    """`readings` as `(reading, type)` pairs, `type` one of "onyomi" /
    "kunyomi" / "nanori"."""
    return kt.KnownItem(
        characters=characters,
        slug=characters,
        object_type="kanji",
        level=1,
        state="known",
        srs_stage=9,
        meanings=[],
        readings=[kt.ReadingOut(reading=r, type=t) for r, t in readings],
        jlpt=None,
    )


def _vocab(characters: str | None, *readings: str, object_type: str = "vocabulary") -> kt.KnownItem:
    return kt.KnownItem(
        characters=characters,
        slug=characters or readings[0],
        object_type=object_type,
        level=1,
        state="known",
        srs_stage=9,
        meanings=[],
        readings=[kt.ReadingOut(reading=r) for r in readings],
        jlpt=None,
    )


def test_onyomi_and_kunyomi_both_become_known_readings() -> None:
    known = build_known_set([_kanji("飲", ("の", "kunyomi"), ("いん", "onyomi"))], [])

    assert known.kanji["飲"] == frozenset({"の", "いん"})
    assert known.knows_kanji("飲") is True
    assert known.knows_kanji("食") is False


def test_nanori_readings_are_excluded() -> None:
    """一's なのり reading かず must not count as a composition candidate --
    it is a name reading, not an ordinary one."""
    known = build_known_set(
        [_kanji("一", ("いち", "onyomi"), ("ひと", "kunyomi"), ("かず", "nanori"))], []
    )

    assert known.kanji["一"] == frozenset({"いち", "ひと"})


def test_kunyomi_with_a_literal_dot_separator_is_stripped_defensively() -> None:
    """Not something kanji-trainer's own data actually contains (see the
    module docstring on `_kanji_known_readings`), but the brief's rule
    describes stripping it, so a future data source that does use it must
    not silently break."""
    known = build_known_set([_kanji("食", ("た.べる", "kunyomi"))], [])

    assert known.kanji["食"] == frozenset({"た"})


def test_vocabulary_known_by_characters_and_reading() -> None:
    known = build_known_set([], [_vocab("先生", "せんせい")])

    assert known.knows_word("先生", "せんせい") is True
    assert known.knows_word("先生", "さきせい") is False
    assert known.knows_word("学生", "がくせい") is False


def test_kana_only_vocabulary_is_keyed_by_its_own_reading() -> None:
    """kana_vocabulary has no `characters` of its own -- analyze() looks
    tokens up by lemma, and a kana-only token's lemma is its reading, so the
    reading has to stand in as the key too."""
    known = build_known_set([], [_vocab(None, "ところ", object_type="kana_vocabulary")])

    assert known.knows_word("ところ", "ところ") is True


def test_multiple_readings_of_one_word_are_all_known() -> None:
    known = build_known_set([], [_vocab("一", "いち", "いつ")])

    assert known.knows_word("一", "いち") is True
    assert known.knows_word("一", "いつ") is True


def test_empty_known_set_knows_nothing() -> None:
    known = KnownSet()

    assert known.knows_kanji("日") is False
    assert known.knows_word("日", "ひ") is False
