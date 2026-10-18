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

from .. import presets, stretch, stretch_store
from ..db import GeneratedText, Suggestion, Topic, get_session
from ..generation import GenerationError, generate_text
from ..models import (
    JlptMixTarget,
    Metrics,
    QuestionOut,
    TextCreateRequest,
    TextOut,
    TextSourceOut,
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


async def _resolve_targets(
    session: AsyncSession, topic: Topic, payload: TextCreateRequest
) -> tuple[TextTargets, float | None]:
    """`targets` plus, only for preset `stretch`, the difficulty `d` its own
    (pre-override) numbers were resolved at -- `None` for `easy`/`challenge`,
    whose numbers never move. `create_text` records both the resolved
    targets and this `d` in the stored `texts.params` (issue #13 brief:
    "The stored params records the resolved values and d.")."""
    preset = presets.get_preset(payload.preset)
    if preset is None:  # pragma: no cover - Literal already restricts this at the API boundary
        raise HTTPException(status_code=422, detail=f"Unknown preset {payload.preset!r}.")

    stretch_d: float | None = None
    preset_unknown_kanji_target = preset.unknown_kanji_target
    preset_jlpt_mix: JlptMixTarget = preset.jlpt_mix
    if payload.preset == "stretch":
        stretch_d = await stretch_store.current_d(session)
        mix = stretch.resolve(stretch_d)
        preset_unknown_kanji_target = mix.unknown_kanji_target
        preset_jlpt_mix = JlptMixTarget(**mix.jlpt_mix)

    overrides = payload.overrides
    style: TopicStyle = (overrides and overrides.style) or topic.default_style  # type: ignore[assignment]
    unknown_kanji_target = (
        overrides.unknown_kanji_target
        if overrides and overrides.unknown_kanji_target is not None
        else preset_unknown_kanji_target
    )
    jlpt_mix: JlptMixTarget = (
        overrides.jlpt_mix if overrides and overrides.jlpt_mix is not None else preset_jlpt_mix
    )

    targets = TextTargets(
        topic_slug=topic.slug,
        length=payload.length,
        preset=payload.preset,
        unknown_kanji_target=unknown_kanji_target,
        jlpt_mix=jlpt_mix,
        style=style,
    )
    return targets, stretch_d


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
        source=TextSourceOut.model_validate(row.source) if row.source else None,
        material_error=row.material_error,
    )


@router.post("", response_model=TextOut, status_code=201)
async def create_text(
    payload: TextCreateRequest, session: AsyncSession = Depends(get_session)
) -> TextOut:
    topic = await _resolve_topic(session, payload.topic_slug)
    targets, stretch_d = await _resolve_targets(session, topic, payload)
    length_chars = presets.get_length(targets.length)
    assert length_chars is not None  # Literal already restricts this

    config = await load_runtime_config(session)

    try:
        outcome = await generate_text(
            config=config,
            kanji_trainer_url=config.kanji_trainer_mcp_url,
            topic_prompt=topic.prompt,
            topic_title=topic.title,
            feed_urls=list(topic.feed_urls or []),
            style=targets.style,
            length_chars=length_chars,
            jlpt_mix=targets.jlpt_mix,
            unknown_kanji_target=targets.unknown_kanji_target,
        )
    except GenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    usage: list[CallUsage] = outcome.calls
    # The `web_search` tool's own flat per-call fee (issue #15) rides on top
    # of the token cost above -- `None` wins (same "unknown model says
    # unknown, never a guessed partial number" rule `pricing.cost_usd`
    # already follows) rather than reporting only the flat fee alone.
    base_cost = cost_usd(outcome.model, usage)
    total_cost = None if base_cost is None else base_cost + outcome.extra_cost_usd
    params = targets.model_dump()
    # `overrides_used` (issue #13) is what `api/sessions.py`'s after-session
    # Stretch rule checks before applying -- "only when ... no JLPT-mix/
    # unknown-kanji overrides" (brief). Extra keys on this dict are simply
    # ignored by `TextTargets.model_validate(row.params)` (`_text_out`
    # below), so this never reaches the browser's `targets` shape.
    params["overrides_used"] = {
        "unknown_kanji_target": bool(
            payload.overrides and payload.overrides.unknown_kanji_target is not None
        ),
        "jlpt_mix": bool(payload.overrides and payload.overrides.jlpt_mix is not None),
    }
    if stretch_d is not None:
        params["stretch_d"] = stretch_d
    row = GeneratedText(
        topic_id=topic.id,
        params=params,
        title=outcome.title,
        body=outcome.body,
        questions=[q.model_dump() for q in outcome.questions],
        analysis=outcome.text_analysis.model_dump(mode="json"),
        known_snapshot=outcome.known_snapshot,
        model=outcome.model,
        usage=[call.as_dict() for call in usage],
        cost_usd=total_cost,
        attempts=outcome.attempts,
        source=outcome.source,
        material_error=outcome.material_error,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    if payload.suggestion_id is not None:
        await _mark_suggestion_used(session, payload.suggestion_id, row, targets)

    return _text_out(row)


async def _mark_suggestion_used(
    session: AsyncSession, suggestion_id: int, row: GeneratedText, targets: TextTargets
) -> None:
    """Mark the suggestion this text was generated from as used -- only
    when `topic_slug`/`length`/`preset` still match it exactly (issue #14
    brief: "a learner who changed things did not 'use' it"). A missing or
    already-used suggestion is silently ignored: generating a text never
    fails over this bookkeeping.
    """
    suggestion = await session.get(Suggestion, suggestion_id)
    if suggestion is None or suggestion.used_text_id is not None:
        return
    payload = suggestion.payload
    if (
        payload.get("topic_slug") != targets.topic_slug
        or payload.get("length") != targets.length
        or payload.get("preset") != targets.preset
    ):
        return
    suggestion.used_text_id = row.id
    await session.commit()


@router.get("/{text_id}", response_model=TextOut)
async def get_text(text_id: int, session: AsyncSession = Depends(get_session)) -> TextOut:
    row = await session.get(GeneratedText, text_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Text not found.")
    return _text_out(row)
