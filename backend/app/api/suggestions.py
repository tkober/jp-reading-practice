"""`POST /api/suggestions` (issue #14): the AI suggestion for what to read
next -- assembles a `SuggestionContext` from the live tables, calls
`app.suggestions.generate_suggestion()`, and stores the result.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import stats_math, stretch, stretch_store
from ..db import GeneratedText, HelpEvent, ReadingSession, Suggestion, Topic, get_session
from ..generation import GenerationError
from ..helps import helps_per_100_words
from ..models import SuggestionOut
from ..pricing import cost_usd
from ..runtime_config import load_runtime_config
from ..suggestion_prompts import (
    RecentSessionInfo,
    StatsSummaryInfo,
    StretchValuesInfo,
    SuggestionContext,
    TopicInfo,
    time_of_day_label,
)
from ..suggestions import SuggestionResult, generate_suggestion

router = APIRouter()

#: The prompt's own "recent sessions" sample -- the brief's own number
#: ("the last 10 finished sessions").
RECENT_SESSIONS_SAMPLE = 10


def _topic_name(text_row: GeneratedText, topics_by_id: dict[int, str], topics_by_slug: dict[str, str]) -> str:
    """Same fallback chain as `api/stats.py`'s own `_topic_name` -- the
    live topic's title, else the slug stored on the text, prettied."""
    if text_row.topic_id is not None and text_row.topic_id in topics_by_id:
        return topics_by_id[text_row.topic_id]
    slug = text_row.params.get("topic_slug", "")
    if slug in topics_by_slug:
        return topics_by_slug[slug]
    return slug.replace("-", " ").capitalize() if slug else ""


async def _finished_session_rows(
    session: AsyncSession,
) -> list[tuple[ReadingSession, GeneratedText]]:
    result = await session.execute(
        select(ReadingSession, GeneratedText)
        .join(GeneratedText, ReadingSession.text_id == GeneratedText.id)
        .where(ReadingSession.status == "finished")
        .order_by(ReadingSession.finished_at.desc(), ReadingSession.id.desc())
    )
    return list(result.all())  # type: ignore[arg-type]


async def _weight_sums(session: AsyncSession, session_ids: list[int]) -> dict[int, int]:
    if not session_ids:
        return {}

    result = await session.execute(
        select(HelpEvent.session_id, func.sum(HelpEvent.weight))
        .where(HelpEvent.session_id.in_(session_ids))
        .group_by(HelpEvent.session_id)
    )
    return {session_id: int(total) for session_id, total in result.all()}


def _to_recent_session_info(
    session_row: ReadingSession,
    text_row: GeneratedText,
    *,
    weight_sum: int,
    topic_name: str,
) -> RecentSessionInfo:
    metrics = text_row.analysis["metrics"]
    active_minutes = session_row.active_ms / 60_000
    chars_per_minute = metrics["characters"] / active_minutes if active_minutes > 0 else 0.0
    questions = text_row.questions
    total = len(questions)
    correct = session_row.comprehension_correct or 0
    comprehension_percent = round(correct / total * 100, 1) if total else 0.0
    assert session_row.finished_at is not None
    return RecentSessionInfo(
        date=session_row.finished_at.date().isoformat(),
        topic=topic_name,
        length=text_row.params.get("length", "short"),
        preset=text_row.params.get("preset", "stretch"),
        style=text_row.params.get("style", ""),
        text_level=stats_math.text_level(metrics.get("jlpt_mix", {})).upper(),
        chars_per_minute=round(chars_per_minute),
        helps_per_100_words=helps_per_100_words(weight_sum, metrics["words"]),
        comprehension_percent=comprehension_percent,
    )


async def _build_context(session: AsyncSession) -> SuggestionContext:
    topic_rows = list(await session.scalars(select(Topic).order_by(Topic.sort_order, Topic.title)))
    topics = [
        TopicInfo(
            slug=row.slug,
            title=row.title,
            style=row.default_style,
            news_backed=bool(row.feed_urls),
        )
        for row in topic_rows
    ]
    topics_by_id = {row.id: row.title for row in topic_rows}
    topics_by_slug = {row.slug: row.title for row in topic_rows}

    finished_rows = await _finished_session_rows(session)
    recent_rows = finished_rows[:RECENT_SESSIONS_SAMPLE]
    weight_sums = await _weight_sums(session, [row.id for row, _ in recent_rows])
    recent_sessions = [
        _to_recent_session_info(
            session_row,
            text_row,
            weight_sum=weight_sums.get(session_row.id, 0),
            topic_name=_topic_name(text_row, topics_by_id, topics_by_slug),
        )
        for session_row, text_row in recent_rows
    ]

    stats: StatsSummaryInfo | None = None
    if len(finished_rows) >= stats_math.STATS_MIN_SESSIONS:
        all_weight_sums = await _weight_sums(session, [row.id for row, _ in finished_rows])
        finished_stats = [
            stats_math.FinishedSessionStat(
                session_id=session_row.id,
                text_id=text_row.id,
                finished_at=session_row.finished_at,  # type: ignore[arg-type]
                chars_per_minute=(
                    text_row.analysis["metrics"]["characters"] / (session_row.active_ms / 60_000)
                    if session_row.active_ms > 0
                    else 0.0
                ),
                helps_per_100_words=helps_per_100_words(
                    all_weight_sums.get(session_row.id, 0), text_row.analysis["metrics"]["words"]
                ),
                comprehension_correct=session_row.comprehension_correct or 0,
                comprehension_total=len(text_row.questions),
                style=text_row.params.get("style", ""),
                topic_name=_topic_name(text_row, topics_by_id, topics_by_slug),
                level=stats_math.text_level(text_row.analysis["metrics"].get("jlpt_mix", {})),
            )
            for session_row, text_row in finished_rows
        ]
        summary = stats_math.compute_summary(finished_stats, now=datetime.now(timezone.utc))
        if summary is not None:
            stats = StatsSummaryInfo(
                reading_level=summary.reading_level,
                reading_level_detail=summary.reading_level_detail,
                speed_delta_percent=summary.speed_delta_percent,
            )

    d = await stretch_store.current_d(session)
    mix = stretch.resolve(d)
    stretch_values = StretchValuesInfo(
        d=d,
        unknown_kanji_target_percent=round(mix.unknown_kanji_target * 100, 1),
        jlpt_mix_percent={level: share * 100 for level, share in mix.jlpt_mix.items()},
    )

    last_session = await session.scalar(
        select(ReadingSession).order_by(ReadingSession.started_at.desc()).limit(1)
    )
    days_since_last_session: int | None = None
    if last_session is not None:
        days_since_last_session = max(
            0, (datetime.now(timezone.utc) - last_session.started_at).days
        )

    return SuggestionContext(
        topics=topics,
        recent_sessions=recent_sessions,
        stats=stats,
        stretch=stretch_values,
        days_since_last_session=days_since_last_session,
        time_of_day=time_of_day_label(datetime.now().hour),
    )


def _suggestion_payload(result: SuggestionResult) -> dict[str, object]:
    return {
        "topic_slug": result.topic_slug,
        "length": result.length,
        "preset": result.preset,
        "overrides": result.overrides.model_dump() if result.overrides else None,
        "reason": result.reason,
    }


@router.post("", response_model=SuggestionOut, status_code=201)
async def create_suggestion(session: AsyncSession = Depends(get_session)) -> SuggestionOut:
    topic_rows = list(await session.scalars(select(Topic)))
    valid_slugs = {row.slug for row in topic_rows}
    if not valid_slugs:
        raise HTTPException(status_code=409, detail="No topics are set up to suggest from.")

    context = await _build_context(session)
    config = await load_runtime_config(session)

    try:
        result = await generate_suggestion(
            config=config, context=context, valid_topic_slugs=valid_slugs
        )
    except GenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    row = Suggestion(
        payload=_suggestion_payload(result),
        reason=result.reason,
        model=result.model,
        usage=[result.usage.as_dict()],
        cost_usd=cost_usd(result.model, [result.usage]),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return SuggestionOut(
        id=row.id,
        topic_slug=result.topic_slug,
        length=result.length,
        preset=result.preset,
        overrides=result.overrides,
        reason=result.reason,
    )
