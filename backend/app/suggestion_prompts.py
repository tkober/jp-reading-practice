"""The system prompt for `POST /api/suggestions` (issue #14): a compact,
English summary of the learner's topics, recent sessions, stats and current
Stretch settings, plus the fixed rules every suggestion has to follow.

Pure and dataclass-driven, same split as `prompts.py`/`help_prompts.py`:
nothing here touches the database or calls an LLM -- `app/suggestions.py`
builds a `SuggestionContext` from the live tables and calls
`build_suggestion_prompt()`, which is what lets this be unit-tested with
hand-built sessions (brief: "context built from hand-built sessions, assert
the prompt contains the right numbers").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TopicInfo:
    """One topic, as the prompt's `# Topics` section lists it."""

    slug: str
    title: str
    style: str
    news_backed: bool


@dataclass(frozen=True)
class RecentSessionInfo:
    """One finished session, newest first in the prompt's `# Recent
    sessions` list -- everything the brief names: "date, topic, length,
    preset, style, text level, 字/min, helps/100 words, comprehension"."""

    date: str
    topic: str
    length: str
    preset: str
    style: str
    text_level: str
    chars_per_minute: int
    helps_per_100_words: float
    comprehension_percent: float


@dataclass(frozen=True)
class StatsSummaryInfo:
    """The Stats page's own reading level/detail, plus speed's trend as the
    same signed percent `stats_math.speed_delta_percent` computes -- `None`
    renders as "no trend data yet" (too few sessions in one of the two
    30-day windows), not a false "stable"."""

    reading_level: str
    reading_level_detail: str
    speed_delta_percent: float | None


@dataclass(frozen=True)
class StretchValuesInfo:
    """Stretch's current resolved mix (`app.stretch.resolve(d)`), as percent
    shares -- the same numbers `GET /api/presets`' own `stretch` entry
    reports, just percent-space here since that is what the prompt and the
    model's own output both work in."""

    d: float
    unknown_kanji_target_percent: float
    jlpt_mix_percent: dict[str, float]


@dataclass(frozen=True)
class SuggestionContext:
    """Everything `build_suggestion_prompt()` needs -- assembled by
    `app/suggestions.py` from the live tables, or by a test directly from
    hand-built values."""

    topics: list[TopicInfo]
    recent_sessions: list[RecentSessionInfo] = field(default_factory=list)
    stats: StatsSummaryInfo | None = None
    stretch: StretchValuesInfo | None = None
    days_since_last_session: int | None = None
    time_of_day: str = "day"


#: Hour ranges (local server time, 0..23) for the prompt's one-word "time of
#: day" -- a rough, non-critical signal (single-user, LAN-only app, see
#: CLAUDE.md's "Known gaps"), not meant to be precise to the learner's own
#: time zone.
_TIME_OF_DAY_RANGES: tuple[tuple[int, int, str], ...] = (
    (5, 11, "morning"),
    (12, 16, "afternoon"),
    (17, 21, "evening"),
)


def time_of_day_label(hour: int) -> str:
    """"morning"/"afternoon"/"evening"/"night" for `hour` (0..23, local
    time) -- night covers the rest (22:00-04:59)."""
    for start, end, label in _TIME_OF_DAY_RANGES:
        if start <= hour <= end:
            return label
    return "night"


_MIX_LABELS: dict[str, str] = {"n5": "N5", "n4": "N4", "n3": "N3", "n2": "N2", "n1": "N1"}
_MIX_ORDER: tuple[str, ...] = ("n5", "n4", "n3", "n2", "n1")


def _mix_sentence(mix: dict[str, float]) -> str:
    parts = [
        f"{_MIX_LABELS[level]} {round(mix.get(level, 0.0))}%" for level in _MIX_ORDER if mix.get(level, 0.0) > 0
    ]
    return ", ".join(parts) if parts else "no particular mix"


def _topics_section(topics: list[TopicInfo]) -> str:
    lines = "\n".join(
        f'- {topic.slug}: "{topic.title}" ({topic.style}, '
        f"{'news-backed' if topic.news_backed else 'not news-backed'})"
        for topic in topics
    )
    return f"""# Topics
{lines}"""


def _recent_sessions_section(sessions: list[RecentSessionInfo]) -> str:
    if len(sessions) < 3:
        count = len(sessions)
        noun = "session" if count == 1 else "sessions"
        intro = (
            f"Only {count} finished {noun} so far -- not enough history for a confident "
            "pick. Suggest a gentle, welcoming start for a learner who is just getting going."
            if count
            else (
                "No finished sessions yet -- this learner is brand new. Suggest a gentle, "
                "welcoming start."
            )
        )
        if not sessions:
            return f"""# Recent sessions
{intro}"""
        lines = "\n".join(_session_line(s) for s in sessions)
        return f"""# Recent sessions
{intro}

{lines}"""

    lines = "\n".join(_session_line(s) for s in sessions)
    return f"""# Recent sessions (newest first)
{lines}"""


def _session_line(s: RecentSessionInfo) -> str:
    return (
        f"- {s.date}: {s.topic}, {s.length}, {s.preset} preset, {s.style}, "
        f"text level {s.text_level}, {round(s.chars_per_minute)} 字/min, "
        f"{s.helps_per_100_words} helps/100 words, {round(s.comprehension_percent)}% comprehension"
    )


def _stats_section(stats: StatsSummaryInfo | None) -> str:
    if stats is None:
        return ""
    if stats.speed_delta_percent is None:
        trend = "no trend data yet"
    else:
        direction = "up" if stats.speed_delta_percent >= 0 else "down"
        trend = f"{direction} {abs(stats.speed_delta_percent):g}% over the last 30 days"
    return f"""

# Stats summary
Reading level: {stats.reading_level} ({stats.reading_level_detail}). Speed trend: {trend}."""


def _stretch_section(stretch: StretchValuesInfo | None) -> str:
    if stretch is None:
        return ""
    return f"""

# Stretch's current settings
Difficulty d={stretch.d:g} (0.5 easiest .. 2.5 hardest). Resolved mix: unknown kanji up to
{stretch.unknown_kanji_target_percent:g}%, JLPT {_mix_sentence(stretch.jlpt_mix_percent)}."""


def _timing_section(days_since_last_session: int | None, time_of_day: str) -> str:
    if days_since_last_session is None:
        gap = "This learner has never read before."
    elif days_since_last_session == 0:
        gap = "The last session was today."
    else:
        day_noun = "day" if days_since_last_session == 1 else "days"
        gap = f"It has been {days_since_last_session} {day_noun} since the last session."
    return f"""

# Timing
{gap} It is currently {time_of_day} for the learner."""


_RULES = """# Rules
- Vary topics: avoid both of the last two topics read, unless the learner keeps choosing
  the same one or two topics on purpose (several recent sessions on it) -- then that
  repetition itself is the evidence to follow, not a reason to force a change.
- Move difficulty only one step at a time: "easy", "stretch" and "challenge" are
  adjacent steps in that order -- never jump from "easy" straight to "challenge".
- Prefer a plain preset over overrides. Only add an override when the evidence above
  gives a clear, specific reason a preset alone would not capture.
- Never suggest the topic "surprise" -- always a real topic from the list above.
- The reason must name the concrete evidence behind the pick (e.g. "your last three
  Travel texts needed few helps, so a step up in difficulty looks safe"), in 1-2
  plain English sentences."""


def build_suggestion_prompt(context: SuggestionContext) -> str:
    """The system prompt for one suggestion call -- everything
    `app/suggestions.py`'s `generate_suggestion()` needs to hand the model,
    assembled from `context` alone (no I/O here, see the module docstring)."""
    return f"""You recommend what a Japanese-reading learner should read next: one topic,
length, difficulty preset, and -- only when clearly justified -- a small override on
top of that preset. You are given the learner's own topics, recent reading history,
overall stats and current adaptive-difficulty settings below; base the suggestion on
that evidence, not on general assumptions about what learners want.

{_topics_section(context.topics)}

{_recent_sessions_section(context.recent_sessions)}{_stats_section(context.stats)}{_stretch_section(context.stretch)}{_timing_section(context.days_since_last_session, context.time_of_day)}

{_RULES}

# Output
Return the suggestion as structured JSON: `topic_slug` (one of the topics' slugs
above, never "surprise"), `length` ("short"/"medium"/"long"), `preset`
("easy"/"stretch"/"challenge"), `overrides` (null unless justified -- `style`,
`unknown_kanji_target_percent` 0-20, and/or `jlpt_mix_percent` summing to 100, each
only when that specific field needs to differ from the preset), and `reason`."""
