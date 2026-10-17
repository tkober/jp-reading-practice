"""Help weights (issue #9), kept in one place per the concept.

A help's weight is what the session summary's `helps_per_100_words` sums
(see `api/sessions.py`): each help kind is counted at most once per word per
session (the unique constraint on `help_events`, see `db.py`), and this
module is the one place that says how much each kind is worth.

`EXPLAIN_WEIGHT`/`TRANSLATE_WEIGHT`/`GRAMMAR_WEIGHT` are wired up by issue
#10's `POST /api/sessions/{id}/assist` (`api/sessions.py`); `TUTOR_WEIGHT`
stays unused until #11 adds the tutor chat. Counted once per *target* per
session, same dedupe shape as `reading_peek`/`word_lookup` (a word's lemma
for `explain`, the sentence key for `translate`/`grammar` -- see
`sentences.py` and `db.HelpEvent`), not per question as an earlier draft of
the concept considered -- per-session dedupe is simpler and the concept's
own counting granularity was never load-bearing for anything else.
"""

from __future__ import annotations

#: A peek at a known word's reading, once per word per session.
READING_PEEK_WEIGHT = 1
#: A tap-to-look-up a word's dictionary entry, once per word per session.
WORD_LOOKUP_WEIGHT = 1

#: Unused until issue #10 (per-question, not per-session -- see the module
#: docstring).
EXPLAIN_WEIGHT = 2
TRANSLATE_WEIGHT = 3
GRAMMAR_WEIGHT = 3
TUTOR_WEIGHT = 3

WEIGHTS: dict[str, int] = {
    "reading_peek": READING_PEEK_WEIGHT,
    "word_lookup": WORD_LOOKUP_WEIGHT,
    "explain": EXPLAIN_WEIGHT,
    "translate": TRANSLATE_WEIGHT,
    "grammar": GRAMMAR_WEIGHT,
    "tutor": TUTOR_WEIGHT,
}


def helps_per_100_words(weight_sum: float, words: int) -> float:
    """A session's `helps_per_100_words`: the sum of its `help_events.weight`
    scaled to a 100-word text, `0.0` for a text with no content words at all
    (never divides by zero). Shared by `api/sessions.py`'s `get_summary` and
    `api/stats.py`'s History/Stats queries (issue #12) so both report the
    exact same number for the exact same session."""
    return round(weight_sum / words * 100, 1) if words else 0.0
