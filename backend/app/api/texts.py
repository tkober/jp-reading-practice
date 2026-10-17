"""Text generation API (issue #8): `POST /api/texts`, `GET /api/texts/{id}`.

`GET /api/texts/{id}/answers` is deliberately NOT added here -- answers are
checked server-side in issue #9, so `answer_index` is stored on the row but
never serialised to the browser (`models.QuestionOut` leaves it out).
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import presets
from ..db import GeneratedText, Topic, get_session
from ..generation import GenerationError, generate_text
from ..models import (
    JlptMixTarget,
    Metrics,
    QuestionOut,
    TextCreateRequest,
    TextOut,
    TextTargets,
    TopicStyle,
)
from ..pricing import CallUsage, cost_usd
from ..runtime_config import load_runtime_config

router = APIRouter()

SURPRISE = "surprise"


async def _resolve_topic(session: AsyncSession, slug: str) -> Topic:
    if slug == SURPRISE:
        rows = list(await session.scalars(select(Topic)))
        if not rows:
            raise HTTPException(status_code=409, detail="No topics are set up to surprise with.")
        return random.choice(rows)  # noqa: S311 - not security sensitive

    row = await session.scalar(select(Topic).where(Topic.slug == slug))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Topic {slug!r} not found.")
    return row


def _resolve_targets(topic: Topic, payload: TextCreateRequest) -> TextTargets:
    preset = presets.get_preset(payload.preset)
    if preset is None:  # pragma: no cover - Literal already restricts this at the API boundary
        raise HTTPException(status_code=422, detail=f"Unknown preset {payload.preset!r}.")

    overrides = payload.overrides
    style: TopicStyle = (overrides and overrides.style) or topic.default_style  # type: ignore[assignment]
    unknown_kanji_target = (
        overrides.unknown_kanji_target
        if overrides and overrides.unknown_kanji_target is not None
        else preset.unknown_kanji_target
    )
    jlpt_mix: JlptMixTarget = (
        overrides.jlpt_mix if overrides and overrides.jlpt_mix is not None else preset.jlpt_mix
    )

    return TextTargets(
        topic_slug=topic.slug,
        length=payload.length,
        preset=payload.preset,
        unknown_kanji_target=unknown_kanji_target,
        jlpt_mix=jlpt_mix,
        style=style,
    )


def _text_out(row: GeneratedText) -> TextOut:
    analysis = row.analysis
    targets = TextTargets.model_validate(row.params)
    questions = [
        QuestionOut(question=q["question"], options=list(q["options"])) for q in row.questions
    ]
    return TextOut(
        id=row.id,
        title=row.title,
        paragraphs=analysis["paragraphs"],
        questions=questions,
        metrics=Metrics.model_validate(analysis["metrics"]),
        targets=targets,
        attempts=row.attempts,
        model=row.model,
        cost_usd=row.cost_usd,
        kanji_trainer_error=row.known_snapshot.get("kanji_trainer_error"),
    )


@router.post("", response_model=TextOut, status_code=201)
async def create_text(
    payload: TextCreateRequest, session: AsyncSession = Depends(get_session)
) -> TextOut:
    topic = await _resolve_topic(session, payload.topic_slug)
    targets = _resolve_targets(topic, payload)
    length_chars = presets.get_length(targets.length)
    assert length_chars is not None  # Literal already restricts this

    config = await load_runtime_config(session)

    try:
        outcome = await generate_text(
            config=config,
            kanji_trainer_url=config.kanji_trainer_mcp_url,
            topic_prompt=topic.prompt,
            style=targets.style,
            length_chars=length_chars,
            jlpt_mix=targets.jlpt_mix,
            unknown_kanji_target=targets.unknown_kanji_target,
        )
    except GenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    usage: list[CallUsage] = outcome.calls
    row = GeneratedText(
        topic_id=topic.id,
        params=targets.model_dump(),
        title=outcome.title,
        body=outcome.body,
        questions=[q.model_dump() for q in outcome.questions],
        analysis=outcome.text_analysis.model_dump(mode="json"),
        known_snapshot=outcome.known_snapshot,
        model=outcome.model,
        usage=[call.as_dict() for call in usage],
        cost_usd=cost_usd(outcome.model, usage),
        attempts=outcome.attempts,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _text_out(row)


@router.get("/{text_id}", response_model=TextOut)
async def get_text(text_id: int, session: AsyncSession = Depends(get_session)) -> TextOut:
    row = await session.get(GeneratedText, text_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Text not found.")
    return _text_out(row)
