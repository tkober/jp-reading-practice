"""History, Stats and the JSON export (issue #12).

Every statistic's actual maths lives in `app.stats_math` (pure, unit tested
without a database); this module is only the queries that turn
`reading_sessions`/`texts`/`help_events`/`chat_messages`/`topics` rows into
that module's inputs, plus the three endpoints themselves:

- `GET /api/history` -- every session, oldest first (the frontend's own
  `HistoryScreen` reverses it to show newest first).
- `GET /api/stats` -- the Stats page's summary tiles, two trend series,
  two "speed by ..." bar charts and the problem-words table, all `None`/
  empty together under `stats_math.STATS_MIN_SESSIONS` finished sessions.
- `GET /api/export` -- every row the learner has ever generated or done,
  for the History page's "Export JSON" button.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import dictionary, stats_math
from ..db import ChatMessage, GeneratedText, HelpEvent, ReadingSession, Topic, get_session
from ..helps import helps_per_100_words
from ..models import (
    ExportChatMessageOut,
    ExportHelpEventOut,
    ExportOut,
    ExportSessionOut,
    ExportTextOut,
    ExportTopicOut,
    HistoryEntryOut,
    ProblemWordOut,
    SeriesPointOut,
    SpeedByGroupOut,
    StatsOut,
    StatsSummaryOut,
)

router = APIRouter()

#: Fixed display order for "Speed by style" -- the concept's own order
#: (casual, the default, through formal), not alphabetical or by value.
STYLE_ORDER = ("casual", "polite", "formal")

#: Help kinds that name a looked-up-or-explained *word* -- what "problem
#: words" counts (brief: "lemmas looked up (`word_lookup` or `explain`)").
PROBLEM_WORD_KINDS = ("word_lookup", "explain")


def _topic_name(
    text_row: GeneratedText, topics_by_id: dict[int, str], topics_by_slug: dict[str, str]
) -> str:
    """The topic's own title when it still exists (by id, the live FK), the
    slug's title when a *different* topic was later created with the same
    slug, or the slug itself, prettied up (`"daily-life"` -> `"Daily
    life"`) -- a text's `topic_id` goes `NULL` when its topic is deleted
    (`ON DELETE SET NULL`, see `db.GeneratedText`), but `params.topic_slug`
    survives for exactly this case."""
    if text_row.topic_id is not None and text_row.topic_id in topics_by_id:
        return topics_by_id[text_row.topic_id]
    slug = text_row.params.get("topic_slug", "")
    if slug in topics_by_slug:
        return topics_by_slug[slug]
    return slug.replace("-", " ").capitalize() if slug else ""


async def _load_rows(session: AsyncSession) -> list[tuple[ReadingSession, GeneratedText]]:
    result = await session.execute(
        select(ReadingSession, GeneratedText)
        .join(GeneratedText, ReadingSession.text_id == GeneratedText.id)
        .order_by(ReadingSession.started_at, ReadingSession.id)
    )
    return list(result.all())  # type: ignore[arg-type]


async def _weight_sums(session: AsyncSession) -> dict[int, int]:
    """`session_id -> sum(help_events.weight)`, one aggregate query shared
    by every session rather than N+1 per-session queries."""
    result = await session.execute(
        select(HelpEvent.session_id, func.sum(HelpEvent.weight)).group_by(HelpEvent.session_id)
    )
    return {session_id: int(total) for session_id, total in result.all()}


async def _topic_maps(session: AsyncSession) -> tuple[dict[int, str], dict[str, str]]:
    rows = list(await session.scalars(select(Topic)))
    return {row.id: row.title for row in rows}, {row.slug: row.title for row in rows}


def _finished_stat(
    session_row: ReadingSession,
    text_row: GeneratedText,
    *,
    weight_sum: int,
    topic_name: str,
) -> stats_math.FinishedSessionStat:
    metrics = text_row.analysis["metrics"]
    active_minutes = session_row.active_ms / 60_000
    chars_per_minute = metrics["characters"] / active_minutes if active_minutes > 0 else 0.0
    questions = text_row.questions
    assert session_row.finished_at is not None  # caller only passes finished rows
    return stats_math.FinishedSessionStat(
        session_id=session_row.id,
        text_id=text_row.id,
        finished_at=session_row.finished_at,
        chars_per_minute=chars_per_minute,
        helps_per_100_words=helps_per_100_words(weight_sum, metrics["words"]),
        comprehension_correct=session_row.comprehension_correct or 0,
        comprehension_total=len(questions),
        style=text_row.params.get("style", ""),
        topic_name=topic_name,
        level=stats_math.text_level(metrics.get("jlpt_mix", {})),
    )


@router.get("/history", response_model=list[HistoryEntryOut])
async def get_history(session: AsyncSession = Depends(get_session)) -> list[HistoryEntryOut]:
    rows = await _load_rows(session)
    weight_sums = await _weight_sums(session)
    topics_by_id, topics_by_slug = await _topic_maps(session)

    entries: list[HistoryEntryOut] = []
    for session_row, text_row in rows:
        finished = session_row.status == "finished"
        metrics = text_row.analysis["metrics"]
        speed = helps = None
        correct = total = None
        if finished:
            active_minutes = session_row.active_ms / 60_000
            speed = (
                round(metrics["characters"] / active_minutes) if active_minutes > 0 else 0
            )
            helps = helps_per_100_words(weight_sums.get(session_row.id, 0), metrics["words"])
            total = len(text_row.questions)
            correct = session_row.comprehension_correct or 0

        entries.append(
            HistoryEntryOut(
                id=session_row.id,
                date=session_row.started_at.date().isoformat(),
                title=text_row.title,
                topic_name=_topic_name(text_row, topics_by_id, topics_by_slug),
                length=text_row.params.get("length", "short"),
                finished=finished,
                speed_chars_per_minute=speed,
                helps_per_100_words=helps,
                comprehension_correct=correct,
                comprehension_total=total,
            )
        )
    return entries


@router.get("/stats", response_model=StatsOut)
async def get_stats(session: AsyncSession = Depends(get_session)) -> StatsOut:
    rows = await _load_rows(session)
    finished_rows = [
        (session_row, text_row) for session_row, text_row in rows if session_row.status == "finished"
    ]

    weight_sums = await _weight_sums(session)
    topics_by_id, topics_by_slug = await _topic_maps(session)

    finished_stats = [
        _finished_stat(
            session_row,
            text_row,
            weight_sum=weight_sums.get(session_row.id, 0),
            topic_name=_topic_name(text_row, topics_by_id, topics_by_slug),
        )
        for session_row, text_row in finished_rows
    ]

    summary = stats_math.compute_summary(finished_stats, now=datetime.now(timezone.utc))
    if summary is None:
        return StatsOut(summary=None)

    speed_by_style_values = stats_math.group_median_speed(finished_stats, "style")
    speed_by_style = [
        SpeedByGroupOut(label=style.capitalize(), value=round(speed_by_style_values[style]))
        for style in STYLE_ORDER
        if style in speed_by_style_values
    ]

    speed_by_topic_values = stats_math.group_median_speed(finished_stats, "topic_name")
    speed_by_topic = [
        SpeedByGroupOut(label=topic, value=round(value))
        for topic, value in sorted(speed_by_topic_values.items())
    ]

    problem_words = await _problem_words(session, finished_rows)

    return StatsOut(
        summary=StatsSummaryOut(
            speed_chars_per_minute=summary.speed_chars_per_minute,
            speed_delta_percent=summary.speed_delta_percent,
            helps_per_100_words=summary.helps_per_100_words,
            comprehension_percent=summary.comprehension_percent,
            reading_level=summary.reading_level,
            reading_level_detail=summary.reading_level_detail,
        ),
        speed_series=[SeriesPointOut(date=date, value=round(value)) for date, value in stats_math.speed_series(finished_stats)],
        helps_series=[SeriesPointOut(date=date, value=value) for date, value in stats_math.helps_series(finished_stats)],
        speed_by_style=speed_by_style,
        speed_by_topic=speed_by_topic,
        problem_words=problem_words,
    )


async def _problem_words(
    session: AsyncSession, finished_rows: list[tuple[ReadingSession, GeneratedText]]
) -> list[ProblemWordOut]:
    """Lemmas looked up/explained in >= `stats_math.PROBLEM_WORD_MIN_TEXTS`
    distinct texts, most-looked-up-first, top `PROBLEM_WORD_TOP_N` -- see
    `stats_math.problem_word_counts` for the counting itself."""
    session_ids = [session_row.id for session_row, _ in finished_rows]
    if not session_ids:
        return []

    text_by_session = {session_row.id: text_row for session_row, text_row in finished_rows}

    help_rows = list(
        await session.scalars(
            select(HelpEvent).where(
                HelpEvent.session_id.in_(session_ids), HelpEvent.kind.in_(PROBLEM_WORD_KINDS)
            )
        )
    )

    occurrences: list[tuple[str, int]] = []
    # First occurrence (lowest help_events.id) of each lemma, so the
    # reading/gloss shown is the earliest-seen one -- an arbitrary but
    # stable tie-break, since the lemma's reading does not vary in
    # practice.
    first_seen: dict[str, HelpEvent] = {}
    for row in help_rows:
        text_row = text_by_session.get(row.session_id)
        if text_row is None:
            continue
        occurrences.append((row.lemma, text_row.id))
        if row.lemma not in first_seen:
            first_seen[row.lemma] = row

    counted = stats_math.problem_word_counts(occurrences)

    results: list[ProblemWordOut] = []
    for lemma, count in counted:
        event = first_seen[lemma]
        text_row = text_by_session[event.session_id]
        reading = _token_lemma_reading(text_row, event.token_id) or ""
        entry = dictionary.lookup(lemma, reading) if reading else None
        meaning = entry.glosses[0] if entry and entry.glosses else ""
        results.append(
            ProblemWordOut(word=lemma, reading=reading, meaning=meaning, times_looked_up=count)
        )
    return results


def _token_lemma_reading(text_row: GeneratedText, token_id: str) -> str | None:
    for paragraph in text_row.analysis["paragraphs"]:
        for token in paragraph["tokens"]:
            if token["id"] == token_id:
                return token.get("lemma_reading") or token["reading"]
    return None


@router.get("/export", response_model=ExportOut)
async def get_export(session: AsyncSession = Depends(get_session)) -> ExportOut:
    topic_rows = list(await session.scalars(select(Topic)))
    text_rows = list(await session.scalars(select(GeneratedText)))
    session_rows = list(await session.scalars(select(ReadingSession)))
    help_rows = list(await session.scalars(select(HelpEvent)))
    chat_rows = list(await session.scalars(select(ChatMessage)))

    return ExportOut(
        exported_at=datetime.now(timezone.utc),
        topics=[
            ExportTopicOut(
                id=row.id,
                slug=row.slug,
                title=row.title,
                glyph=row.glyph,
                prompt=row.prompt,
                default_style=row.default_style,
                feed_urls=list(row.feed_urls or []),
                is_builtin=row.is_builtin,
                is_customized=row.is_customized,
            )
            for row in topic_rows
        ],
        texts=[
            ExportTextOut(
                id=row.id,
                topic_id=row.topic_id,
                title=row.title,
                body=row.body,
                questions=list(row.questions),
                params=dict(row.params),
                model=row.model,
                cost_usd=row.cost_usd,
                created_at=row.created_at,
            )
            for row in text_rows
        ],
        sessions=[
            ExportSessionOut(
                id=row.id,
                text_id=row.text_id,
                status=row.status,  # type: ignore[arg-type]
                started_at=row.started_at,
                reading_finished_at=row.reading_finished_at,
                finished_at=row.finished_at,
                active_ms=row.active_ms,
                paused_ms=row.paused_ms,
                answers=list(row.answers),
                comprehension_correct=row.comprehension_correct,
            )
            for row in session_rows
        ],
        help_events=[
            ExportHelpEventOut(
                id=row.id,
                session_id=row.session_id,
                kind=row.kind,
                target=row.target,
                token_id=row.token_id,
                lemma=row.lemma,
                surface=row.surface,
                weight=row.weight,
                cost_usd=row.cost_usd,
                created_at=row.created_at,
            )
            for row in help_rows
        ],
        chat_messages=[
            ExportChatMessageOut(
                id=row.id,
                session_id=row.session_id,
                role=row.role,  # type: ignore[arg-type]
                content=row.content,
                focus_sentence_key=row.focus_sentence_key,
                model=row.model,
                cost_usd=row.cost_usd,
                created_at=row.created_at,
            )
            for row in chat_rows
        ],
    )
