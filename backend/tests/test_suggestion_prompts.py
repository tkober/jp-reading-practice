"""`app.suggestion_prompts` (issue #14): pure prompt building from hand-built
contexts -- no database, no LLM, same spirit as `test_stretch.py`/
`test_stats_math.py`. Asserts the prompt actually contains the numbers each
section is supposed to carry, and the two "not enough history" wordings."""

from __future__ import annotations

from app.suggestion_prompts import (
    RecentSessionInfo,
    StatsSummaryInfo,
    StretchValuesInfo,
    SuggestionContext,
    TopicInfo,
    build_suggestion_prompt,
    time_of_day_label,
)

TOPICS = [
    TopicInfo(slug="daily-life", title="Daily life", style="casual", news_backed=False),
    TopicInfo(slug="current-events", title="Current events", style="formal", news_backed=True),
]


def _session(**overrides: object) -> RecentSessionInfo:
    defaults: dict[str, object] = dict(
        date="2026-10-10",
        topic="Travel",
        length="medium",
        preset="stretch",
        style="polite",
        text_level="N3",
        chars_per_minute=132,
        helps_per_100_words=4.2,
        comprehension_percent=85.0,
    )
    defaults.update(overrides)
    return RecentSessionInfo(**defaults)  # type: ignore[arg-type]


# --- topics ------------------------------------------------------------------


def test_topics_section_lists_slug_title_style_and_news_backing() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS))
    assert "daily-life" in prompt
    assert '"Daily life"' in prompt
    assert "casual" in prompt
    assert "not news-backed" in prompt
    assert "current-events" in prompt
    assert '"Current events"' in prompt
    assert "news-backed" in prompt


# --- recent sessions ----------------------------------------------------------


def test_recent_sessions_section_carries_every_number() -> None:
    sessions = [_session(topic="Travel", chars_per_minute=132, helps_per_100_words=4.2, comprehension_percent=85.0)]
    sessions.extend(_session() for _ in range(2))  # 3 total, clears the "insufficient" threshold
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, recent_sessions=sessions))
    assert "Travel" in prompt
    assert "132" in prompt
    assert "4.2 helps/100 words" in prompt
    assert "85% comprehension" in prompt
    assert "N3" in prompt
    assert "stretch preset" in prompt
    assert "2026-10-10" in prompt


def test_fewer_than_three_sessions_asks_for_a_gentle_start() -> None:
    sessions = [_session(), _session()]
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, recent_sessions=sessions))
    assert "Only 2 finished sessions" in prompt
    assert "gentle" in prompt


def test_zero_sessions_says_brand_new() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, recent_sessions=[]))
    assert "brand new" in prompt
    assert "No finished sessions yet" in prompt


def test_exactly_three_sessions_is_not_flagged_as_insufficient() -> None:
    sessions = [_session() for _ in range(3)]
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, recent_sessions=sessions))
    assert "finished sessions so far" not in prompt
    assert "newest first" in prompt


# --- stats summary ------------------------------------------------------------


def test_stats_section_reports_an_upward_trend() -> None:
    stats = StatsSummaryInfo(reading_level="N4", reading_level_detail="comfortable", speed_delta_percent=12.5)
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, stats=stats))
    assert "Reading level: N4 (comfortable)" in prompt
    assert "up 12.5%" in prompt


def test_stats_section_reports_a_downward_trend() -> None:
    stats = StatsSummaryInfo(reading_level="N3", reading_level_detail="with help", speed_delta_percent=-6.0)
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, stats=stats))
    assert "down 6%" in prompt


def test_stats_section_with_no_trend_data() -> None:
    stats = StatsSummaryInfo(reading_level="N5", reading_level_detail="comfortable", speed_delta_percent=None)
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, stats=stats))
    assert "no trend data yet" in prompt


def test_stats_section_absent_when_no_summary() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, stats=None))
    assert "# Stats summary" not in prompt


# --- stretch -------------------------------------------------------------------


def test_stretch_section_reports_d_and_mix() -> None:
    stretch_values = StretchValuesInfo(
        d=1.3, unknown_kanji_target_percent=6.5, jlpt_mix_percent={"n5": 45, "n4": 35, "n3": 20, "n2": 0, "n1": 0}
    )
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, stretch=stretch_values))
    assert "d=1.3" in prompt
    assert "6.5%" in prompt
    assert "N5 45%" in prompt
    assert "N3 20%" in prompt
    assert "N2" not in prompt  # zero shares are left out, same as stretch.describe_mix


# --- timing --------------------------------------------------------------------


def test_timing_section_days_since_last_session() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, days_since_last_session=5, time_of_day="evening"))
    assert "It has been 5 days since the last session." in prompt
    assert "currently evening" in prompt


def test_timing_section_today() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, days_since_last_session=0))
    assert "The last session was today." in prompt


def test_timing_section_never_read_before() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS, days_since_last_session=None))
    assert "This learner has never read before." in prompt


# --- rules / output ------------------------------------------------------------


def test_prompt_tells_the_model_never_to_suggest_surprise() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS))
    assert '"surprise"' in prompt
    assert "never" in prompt.lower()


def test_prompt_asks_for_concrete_evidence_in_the_reason() -> None:
    prompt = build_suggestion_prompt(SuggestionContext(topics=TOPICS))
    assert "concrete evidence" in prompt


# --- time_of_day_label ----------------------------------------------------------


def test_time_of_day_label_boundaries() -> None:
    assert time_of_day_label(4) == "night"
    assert time_of_day_label(5) == "morning"
    assert time_of_day_label(11) == "morning"
    assert time_of_day_label(12) == "afternoon"
    assert time_of_day_label(16) == "afternoon"
    assert time_of_day_label(17) == "evening"
    assert time_of_day_label(21) == "evening"
    assert time_of_day_label(22) == "night"
    assert time_of_day_label(0) == "night"
