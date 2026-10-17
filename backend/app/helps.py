"""Help weights (issue #9), kept in one place per the concept.

A help's weight is what the session summary's `helps_per_100_words` sums
(see `api/sessions.py`): each help kind is counted at most once per word per
session (the unique constraint on `help_events`, see `db.py`), and this
module is the one place that says how much each kind is worth.

`EXPLAIN_WEIGHT`/`TRANSLATE_WEIGHT`/`GRAMMAR_WEIGHT`/`TUTOR_WEIGHT` are not
used by anything yet -- issue #10 adds the endpoints that log them -- but
are defined here now, from the concept, so they land in the one obvious
place rather than being invented again once something needs them. Unlike
`reading_peek`/`word_lookup` (counted once per word per *session*), the
concept counts those per word per *question* -- #10's own job to implement,
not this module's.
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
