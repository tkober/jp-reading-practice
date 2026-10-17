"""`app/dictionary.py` -- JMdict lookup for the word popover (issue #7).

Skips with a clear reason if `app/data/jmdict.sqlite` has not been built
(see `scripts/build_jmdict.py` and the README) -- but this environment
built it as part of the issue #7 work, so the suite actually runs it rather
than only exercising the "not built" fallback.
"""

from __future__ import annotations

import pytest

from app import dictionary

pytestmark = pytest.mark.skipif(
    not dictionary.DB_PATH.exists(),
    reason=(
        "app/data/jmdict.sqlite has not been built -- run "
        "`uv run python scripts/build_jmdict.py` from backend/ first."
    ),
)


def test_lookup_finds_a_common_verb_with_pos_and_glosses() -> None:
    entry = dictionary.lookup("食べる", "たべる")

    assert entry is not None
    assert entry.lemma == "食べる"
    assert entry.reading == "たべる"
    assert "to eat" in entry.glosses
    assert len(entry.glosses) <= 3
    assert any("verb" in tag for tag in entry.pos)


def test_lookup_a_proper_noun_place_name() -> None:
    entry = dictionary.lookup("金沢", "かなざわ")

    assert entry is not None
    assert "Kanazawa" in entry.glosses[0]


def test_lookup_returns_none_for_an_unknown_pair() -> None:
    assert dictionary.lookup("食べる", "まったくちがうよみ") is None


def test_lookup_is_exact_on_reading_not_just_lemma() -> None:
    # 一 is read いち in some entries and いつ in others -- a reading that
    # does not belong to this lemma at all must not match either.
    assert dictionary.lookup("一", "ぜんぜんちがう") is None
