"""Pure statistics maths (issue #12) -- no database, no app, just
`app.stats_math`'s functions against hand-built `FinishedSessionStat`s."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.stats_math import (
    FinishedSessionStat,
    compute_summary,
    group_median_speed,
    helps_and_comprehension,
    median,
    problem_word_counts,
    reading_level,
    speed_delta_percent,
    speed_median,
    speed_series,
    text_level,
)

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def _stat(
    *,
    session_id: int = 1,
    text_id: int = 1,
    days_ago: float = 0,
    chars_per_minute: float = 120.0,
    helps_per_100_words: float = 5.0,
    comprehension_correct: int = 3,
    comprehension_total: int = 3,
    style: str = "casual",
    topic_name: str = "Daily life",
    level: str = "n4",
) -> FinishedSessionStat:
    return FinishedSessionStat(
        session_id=session_id,
        text_id=text_id,
        finished_at=NOW - timedelta(days=days_ago),
        chars_per_minute=chars_per_minute,
        helps_per_100_words=helps_per_100_words,
        comprehension_correct=comprehension_correct,
        comprehension_total=comprehension_total,
        style=style,
        topic_name=topic_name,
        level=level,
    )


# --- median / text_level -----------------------------------------------------


def test_median_of_empty_is_none() -> None:
    assert median([]) is None


def test_median_of_values() -> None:
    assert median([1, 2, 3]) == 2
    assert median([1, 2, 3, 4]) == 2.5


def test_text_level_picks_highest_level_at_or_above_threshold() -> None:
    # N3 at exactly 10%, N2 below -- N3 wins (highest that clears the bar).
    assert text_level({"n5": 0.5, "n4": 0.2, "n3": 0.10, "n2": 0.05, "n1": 0.0}) == "n3"


def test_text_level_defaults_to_n5_when_nothing_clears_the_threshold() -> None:
    assert text_level({"n5": 0.05, "n4": 0.05, "n3": 0.0, "n2": 0.0, "n1": 0.0}) == "n5"


def test_text_level_missing_keys_treated_as_zero() -> None:
    assert text_level({}) == "n5"


# --- speed / delta / helps+comprehension -------------------------------------


def test_speed_median_over_last_10_sessions() -> None:
    # 11 sessions, speeds 100..110 one day apart -- the median of the most
    # recent 10 (101..110) excludes the oldest (100).
    sessions = [_stat(days_ago=i, chars_per_minute=110 - i) for i in range(11)]
    assert speed_median(sessions) == 105.5


def test_speed_delta_percent_compares_last_30_days_to_the_30_before() -> None:
    recent = [_stat(days_ago=5, chars_per_minute=120), _stat(days_ago=25, chars_per_minute=140)]
    prior = [_stat(days_ago=35, chars_per_minute=100), _stat(days_ago=55, chars_per_minute=100)]
    delta = speed_delta_percent(recent + prior, now=NOW)
    # recent mean 130, prior mean 100 -> +30%.
    assert delta == 30.0


def test_speed_delta_percent_is_none_without_both_windows() -> None:
    only_recent = [_stat(days_ago=5)]
    assert speed_delta_percent(only_recent, now=NOW) is None


def test_helps_and_comprehension_pools_correct_over_total() -> None:
    sessions = [
        _stat(comprehension_correct=2, comprehension_total=2, helps_per_100_words=4.0),
        _stat(comprehension_correct=0, comprehension_total=3, helps_per_100_words=6.0),
    ]
    helps, comprehension = helps_and_comprehension(sessions)
    assert helps == 5.0  # median(4, 6)
    # Pooled: 2 correct / 5 total = 40%, not (100% + 0%) / 2 = 50%.
    assert comprehension == 40.0


# --- series -------------------------------------------------------------------


def test_speed_series_is_oldest_first_and_capped_at_30() -> None:
    sessions = [_stat(days_ago=i, chars_per_minute=100 + i) for i in range(35)]
    series = speed_series(sessions)
    assert len(series) == 30
    # Oldest included session is 29 days ago (the most recent 30 of 35).
    assert series[0] == ((NOW - timedelta(days=29)).date().isoformat(), 129)
    assert series[-1] == (NOW.date().isoformat(), 100)


# --- group_median_speed -------------------------------------------------------


def test_group_median_speed_by_style() -> None:
    sessions = [
        _stat(style="casual", chars_per_minute=100),
        _stat(style="casual", chars_per_minute=120),
        _stat(style="formal", chars_per_minute=80),
    ]
    result = group_median_speed(sessions, "style")
    assert result == {"casual": 110, "formal": 80}


def test_group_median_speed_skips_empty_group_key() -> None:
    sessions = [_stat(topic_name=""), _stat(topic_name="History")]
    result = group_median_speed(sessions, "topic_name")
    assert result == {"History": sessions[1].chars_per_minute}


# --- problem_word_counts ------------------------------------------------------


def test_problem_word_counts_requires_two_distinct_texts() -> None:
    occurrences = [("食べる", 1), ("食べる", 1), ("食べる", 2), ("飲む", 1)]
    result = problem_word_counts(occurrences)
    assert result == [("食べる", 2)]  # 飲む only in one text, excluded


def test_problem_word_counts_sorted_most_first_then_alphabetical() -> None:
    occurrences = [
        ("b", 1), ("b", 2),
        ("a", 1), ("a", 2), ("a", 3),
        ("c", 1), ("c", 2),
    ]
    result = problem_word_counts(occurrences)
    assert result == [("a", 3), ("b", 2), ("c", 2)]


def test_problem_word_counts_caps_at_top_20() -> None:
    occurrences = [(f"word{i}", text) for i in range(25) for text in (1, 2)]
    result = problem_word_counts(occurrences)
    assert len(result) == 20


# --- reading_level -------------------------------------------------------------


def test_reading_level_comfortable_with_next_level_with_help() -> None:
    # N4: 5 sessions, low helps, high comprehension -> comfortable.
    n4_sessions = [
        _stat(level="n4", days_ago=i, helps_per_100_words=3.0, comprehension_correct=3, comprehension_total=3)
        for i in range(5)
    ]
    # N3 (the next harder level): comprehension clears 80% but helps is high -> with help.
    n3_sessions = [
        _stat(level="n3", days_ago=i, helps_per_100_words=8.0, comprehension_correct=3, comprehension_total=3)
        for i in range(5)
    ]
    result = reading_level(n4_sessions + n3_sessions)
    assert result.level == "N4"
    assert result.detail == "comfortable · N3 with help"
    assert result.statuses["n4"] == "comfortable"
    assert result.statuses["n3"] == "with_help"


def test_reading_level_comfortable_without_next_level_data() -> None:
    n4_sessions = [
        _stat(level="n4", days_ago=i, helps_per_100_words=2.0, comprehension_correct=3, comprehension_total=3)
        for i in range(5)
    ]
    result = reading_level(n4_sessions)
    assert result.level == "N4"
    assert result.detail == "comfortable"


def test_reading_level_with_help_only_when_nothing_is_comfortable() -> None:
    n4_sessions = [
        _stat(level="n4", days_ago=i, helps_per_100_words=9.0, comprehension_correct=3, comprehension_total=3)
        for i in range(5)
    ]
    result = reading_level(n4_sessions)
    assert result.level == "—"
    assert result.detail == "with help at N4"


def test_reading_level_not_enough_sessions_per_level() -> None:
    # Only 2 sessions at N4 -- below READING_LEVEL_MIN_SESSIONS.
    n4_sessions = [_stat(level="n4", days_ago=i) for i in range(2)]
    result = reading_level(n4_sessions)
    assert result.level == "—"
    assert result.detail == "not enough sessions per level yet"


def test_reading_level_struggling_is_neither_comfortable_nor_with_help() -> None:
    n4_sessions = [
        _stat(level="n4", days_ago=i, helps_per_100_words=2.0, comprehension_correct=1, comprehension_total=3)
        for i in range(5)
    ]
    result = reading_level(n4_sessions)
    assert result.statuses["n4"] == "struggling"
    assert result.level == "—"
    assert result.detail == "not enough sessions per level yet"


def test_reading_level_uses_only_the_last_5_sessions_per_level() -> None:
    # 6 old sessions struggling, then 5 recent comfortable ones -- only the
    # most recent 5 should count.
    old = [
        _stat(level="n4", days_ago=100 + i, helps_per_100_words=20.0, comprehension_correct=0, comprehension_total=3)
        for i in range(6)
    ]
    recent = [
        _stat(level="n4", days_ago=i, helps_per_100_words=1.0, comprehension_correct=3, comprehension_total=3)
        for i in range(5)
    ]
    result = reading_level(old + recent)
    assert result.statuses["n4"] == "comfortable"


# --- compute_summary -----------------------------------------------------------


def test_compute_summary_is_none_under_minimum_sessions() -> None:
    assert compute_summary([_stat(), _stat()], now=NOW) is None


def test_compute_summary_combines_every_statistic() -> None:
    sessions = [_stat(days_ago=i, chars_per_minute=100 + i) for i in range(5)]
    summary = compute_summary(sessions, now=NOW)
    assert summary is not None
    assert summary.speed_chars_per_minute == round(speed_median(sessions))
    assert summary.reading_level in {"N4", "—"}
