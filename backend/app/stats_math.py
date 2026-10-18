"""Pure statistics maths for History/Stats (issue #12).

Nothing here touches the database -- `api/stats.py` builds `FinishedSessionStat`
rows from `reading_sessions`/`texts`/`help_events` and hands them to the
functions below, which is what makes the reading-level/median/delta logic
unit-testable without a database at all (see `tests/test_stats_math.py`).

Every constant the concept named a number for lives here, in one place, with
the decision it encodes written out next to it -- `api/stats.py` imports
these rather than repeating the numbers.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

#: A text's own JLPT level (`text_level`) is the highest level with at least
#: this share of its content words -- below this, that level's words are
#: too few to call the text "that level" (issue #12 concept).
LEVEL_SHARE_THRESHOLD = 0.10

#: Reading level (`reading_level`) looks at each level's last this-many
#: finished sessions.
READING_LEVEL_SAMPLE_SESSIONS = 5
#: ... and needs at least this many of them before it says anything about
#: that level at all (fewer is not a trend, just noise).
READING_LEVEL_MIN_SESSIONS = 3
#: "Comfortable" requires the sampled sessions' median helps/100 words at or
#: under this.
READING_LEVEL_HELPS_MAX = 5.0
#: ... and comprehension (correct / total questions, pooled over the sample)
#: at or above this, for either "comfortable" or "with help".
READING_LEVEL_COMPREHENSION_MIN = 0.80

#: The whole Stats page is the empty state under this many finished sessions.
STATS_MIN_SESSIONS = 3
#: Speed's own big number is the median over the last this-many finished
#: sessions.
SPEED_SAMPLE_SESSIONS = 10
#: Helps/100 words and comprehension are over the last this-many finished
#: sessions (comprehension pooled: total correct / total questions across
#: them, not an average of per-session percentages).
HELPS_SAMPLE_SESSIONS = 10
#: The two trend charts plot the last this-many finished sessions, oldest
#: left.
SERIES_SAMPLE_SESSIONS = 30
#: Speed's delta compares the mean of the last this-many days against the
#: this-many days before that.
DELTA_WINDOW_DAYS = 30
#: A lemma only becomes a "problem word" once looked up/explained in at
#: least this many distinct texts.
PROBLEM_WORD_MIN_TEXTS = 2
PROBLEM_WORD_TOP_N = 20

#: Hardest first -- N1 is the hardest JLPT level, N5 the easiest. Every
#: level-ordering decision in this module (text_level's own scan,
#: reading_level's "highest comfortable level", "next higher level") walks
#: this tuple in this order, so "first match" always means "hardest/highest
#: match".
LEVEL_ORDER: tuple[str, ...] = ("n1", "n2", "n3", "n4", "n5")


def text_level(jlpt_mix: Mapping[str, float]) -> str:
    """A text's own level: the highest (hardest) JLPT level with a measured
    share >= `LEVEL_SHARE_THRESHOLD` in its `metrics.jlpt_mix`, N5 when none
    of N1..N4 reaches that share. Returns a lowercase key (`"n4"`), matching
    `LEVEL_ORDER` and `FinishedSessionStat.level` -- callers display it
    uppercased (`"N4"`)."""
    for level in LEVEL_ORDER:
        if jlpt_mix.get(level, 0.0) >= LEVEL_SHARE_THRESHOLD:
            return level
    return "n5"


def median(values: Sequence[float]) -> float | None:
    """`None` for an empty sequence rather than raising -- every caller here
    already knows when that means "not enough data" vs. "zero"."""
    if not values:
        return None
    return statistics.median(values)


@dataclass(frozen=True)
class FinishedSessionStat:
    """One finished reading session's measurements, decoupled from the ORM
    rows `api/stats.py`'s queries build this from -- what every pure
    function below actually takes.

    `chars_per_minute`/`helps_per_100_words` are already the per-session
    numbers (same maths as `api/sessions.py`'s `get_summary`, computed once
    per session rather than re-derived here); `comprehension_correct`/
    `comprehension_total` are pooled across a sample by summing both sides
    before dividing, never averaged per-session, so a 2/2 session and a 0/3
    session together read as 2/5 (40%), not (100% + 0%) / 2 = 50%.
    """

    session_id: int
    text_id: int
    finished_at: datetime
    chars_per_minute: float
    helps_per_100_words: float
    comprehension_correct: int
    comprehension_total: int
    style: str
    topic_name: str
    #: Lowercase, `LEVEL_ORDER`'s own key shape (`text_level`'s return value).
    level: str


def _most_recent(sessions: Sequence[FinishedSessionStat], n: int) -> list[FinishedSessionStat]:
    return sorted(sessions, key=lambda s: s.finished_at, reverse=True)[:n]


def speed_median(sessions: Sequence[FinishedSessionStat]) -> float | None:
    """Median `chars_per_minute` over the last `SPEED_SAMPLE_SESSIONS`."""
    recent = _most_recent(sessions, SPEED_SAMPLE_SESSIONS)
    return median([s.chars_per_minute for s in recent])


def speed_delta_percent(sessions: Sequence[FinishedSessionStat], *, now: datetime) -> float | None:
    """Mean `chars_per_minute` over the last `DELTA_WINDOW_DAYS` vs. the
    `DELTA_WINDOW_DAYS` before that, as a signed percent change -- `None`
    when either window has no finished session (a change needs two points)."""
    window_start = now - timedelta(days=DELTA_WINDOW_DAYS)
    prior_start = now - timedelta(days=2 * DELTA_WINDOW_DAYS)

    recent = [s.chars_per_minute for s in sessions if s.finished_at >= window_start]
    prior = [s.chars_per_minute for s in sessions if prior_start <= s.finished_at < window_start]
    if not recent or not prior:
        return None

    recent_mean = statistics.mean(recent)
    prior_mean = statistics.mean(prior)
    if prior_mean == 0:
        return None
    return round((recent_mean - prior_mean) / prior_mean * 100, 1)


def helps_and_comprehension(sessions: Sequence[FinishedSessionStat]) -> tuple[float, float]:
    """`(helps_per_100_words, comprehension_percent)` over the last
    `HELPS_SAMPLE_SESSIONS` -- helps is the sample's median (same shape as
    `speed_median`), comprehension is pooled (see `FinishedSessionStat`'s
    docstring), as a 0..100 percent rounded to one decimal."""
    recent = _most_recent(sessions, HELPS_SAMPLE_SESSIONS)
    helps = median([s.helps_per_100_words for s in recent]) or 0.0
    total = sum(s.comprehension_total for s in recent)
    correct = sum(s.comprehension_correct for s in recent)
    comprehension = round(correct / total * 100, 1) if total else 0.0
    return helps, comprehension


def speed_series(sessions: Sequence[FinishedSessionStat]) -> list[tuple[str, float]]:
    """`(iso date, chars_per_minute)` for the last `SERIES_SAMPLE_SESSIONS`
    finished sessions, oldest first."""
    recent = _most_recent(sessions, SERIES_SAMPLE_SESSIONS)
    recent.reverse()
    return [(s.finished_at.date().isoformat(), s.chars_per_minute) for s in recent]


def helps_series(sessions: Sequence[FinishedSessionStat]) -> list[tuple[str, float]]:
    """Same shape and sample as `speed_series`, for `helps_per_100_words`."""
    recent = _most_recent(sessions, SERIES_SAMPLE_SESSIONS)
    recent.reverse()
    return [(s.finished_at.date().isoformat(), s.helps_per_100_words) for s in recent]


def group_median_speed(
    sessions: Sequence[FinishedSessionStat], key: str
) -> dict[str, float]:
    """Median `chars_per_minute` per distinct `style`/`topic_name` (whichever
    `key` names), over *every* finished session -- unlike the headline
    numbers above, "speed by style"/"speed by topic" are not limited to a
    recent sample (the concept gives them no window), just "groups with >= 1
    session". Empty/falsy group keys are skipped (nothing to label the bar
    with)."""
    groups: dict[str, list[float]] = {}
    for session_stat in sessions:
        group_key = getattr(session_stat, key)
        if not group_key:
            continue
        groups.setdefault(group_key, []).append(session_stat.chars_per_minute)
    result: dict[str, float] = {}
    for group_key, values in groups.items():
        value = median(values)
        if value is not None:
            result[group_key] = value
    return result


def problem_word_counts(occurrences: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    """`(lemma, distinct text count)` for every lemma looked up/explained in
    at least `PROBLEM_WORD_MIN_TEXTS` different texts, most-looked-up-first
    (ties broken alphabetically, for a stable order), top
    `PROBLEM_WORD_TOP_N`. `occurrences` is `(lemma, text_id)` pairs, one per
    `word_lookup`/`explain` help event -- repeats of the same text do not
    add a second count (a `set` per lemma), only a different text does."""
    texts_by_lemma: dict[str, set[int]] = {}
    for lemma, text_id in occurrences:
        texts_by_lemma.setdefault(lemma, set()).add(text_id)

    counted = [
        (lemma, len(texts))
        for lemma, texts in texts_by_lemma.items()
        if len(texts) >= PROBLEM_WORD_MIN_TEXTS
    ]
    counted.sort(key=lambda pair: (-pair[1], pair[0]))
    return counted[:PROBLEM_WORD_TOP_N]


@dataclass(frozen=True)
class ReadingLevelResult:
    """`reading_level`'s return shape -- `level`/`detail` are exactly what
    the frontend's `StatsSummary.readingLevel`/`readingLevelDetail` show
    (`"N4"`/`"comfortable · N3 with help"`, or `"—"` with one of the two
    "nothing comfortable yet" sentences); `statuses` (every `LEVEL_ORDER`
    key -> `"comfortable" | "with_help" | "struggling" | "insufficient"`) is
    exposed purely so tests can assert on the per-level call directly
    instead of reverse-engineering it from the two display strings."""

    level: str
    detail: str
    statuses: Mapping[str, str]


def _level_status(sample: Sequence[FinishedSessionStat]) -> str:
    if len(sample) < READING_LEVEL_MIN_SESSIONS:
        return "insufficient"
    helps = median([s.helps_per_100_words for s in sample]) or 0.0
    total = sum(s.comprehension_total for s in sample)
    correct = sum(s.comprehension_correct for s in sample)
    comprehension = correct / total if total else 0.0
    if comprehension < READING_LEVEL_COMPREHENSION_MIN:
        return "struggling"
    return "comfortable" if helps <= READING_LEVEL_HELPS_MAX else "with_help"


def reading_level(sessions: Sequence[FinishedSessionStat]) -> ReadingLevelResult:
    """"Reading level": the highest JLPT level whose last
    `READING_LEVEL_SAMPLE_SESSIONS` finished sessions at that level (at
    least `READING_LEVEL_MIN_SESSIONS` of them) are "comfortable" -- median
    helps/100 words at or under `READING_LEVEL_HELPS_MAX` *and* pooled
    comprehension at or above `READING_LEVEL_COMPREHENSION_MIN`.

    No comfortable level yet: `level` is `"—"`; `detail` names the highest
    level that is at least "with help" (comprehension clears the bar, helps
    does not) if one exists, else says there simply are not enough sessions
    per level yet.

    A comfortable level does exist: `detail` adds the next *higher* (harder)
    level's own status when that level is "with help" -- e.g. comfortable at
    N4 with N3 already "with help" reads "comfortable · N3 with help",
    exactly the shape a learner about to move up wants to see.
    """
    statuses = {level: _level_status(_most_recent(
        [s for s in sessions if s.level == level], READING_LEVEL_SAMPLE_SESSIONS
    )) for level in LEVEL_ORDER}

    comfortable = [level for level in LEVEL_ORDER if statuses[level] == "comfortable"]
    if comfortable:
        best = comfortable[0]
        detail = "comfortable"
        index = LEVEL_ORDER.index(best)
        if index > 0:
            higher = LEVEL_ORDER[index - 1]
            if statuses[higher] == "with_help":
                detail = f"comfortable · {higher.upper()} with help"
        return ReadingLevelResult(level=best.upper(), detail=detail, statuses=statuses)

    with_help = [level for level in LEVEL_ORDER if statuses[level] == "with_help"]
    if with_help:
        return ReadingLevelResult(
            level="—", detail=f"with help at {with_help[0].upper()}", statuses=statuses
        )

    return ReadingLevelResult(level="—", detail="not enough sessions per level yet", statuses=statuses)


@dataclass(frozen=True)
class StatsSummaryResult:
    speed_chars_per_minute: int
    speed_delta_percent: float | None
    helps_per_100_words: float
    comprehension_percent: float
    reading_level: str
    reading_level_detail: str


def compute_summary(
    sessions: Sequence[FinishedSessionStat], *, now: datetime
) -> StatsSummaryResult | None:
    """The four `sumi-stat-tile`s' worth of numbers, or `None` under
    `STATS_MIN_SESSIONS` -- the whole Stats page's empty state."""
    if len(sessions) < STATS_MIN_SESSIONS:
        return None

    speed = speed_median(sessions)
    assert speed is not None  # len(sessions) >= STATS_MIN_SESSIONS > 0
    helps, comprehension = helps_and_comprehension(sessions)
    level_result = reading_level(sessions)

    return StatsSummaryResult(
        speed_chars_per_minute=round(speed),
        speed_delta_percent=speed_delta_percent(sessions, now=now),
        helps_per_100_words=helps,
        comprehension_percent=comprehension,
        reading_level=level_result.level,
        reading_level_detail=level_result.detail,
    )
