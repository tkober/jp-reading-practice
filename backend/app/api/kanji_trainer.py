"""`GET /api/kanji-trainer/status` -- the Settings screen's connection test.

Bypasses the client's own cache (a `fresh` call) so the button always tests
the live connection rather than reporting a result from 15 minutes ago, but
still refreshes the cache with whatever it got -- a `KnownItem` list fetched
right after wins nothing from throwing this away.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import kanji_trainer
from ..db import get_session
from ..models import KanjiTrainerStatus
from ..runtime_config import load_runtime_config

router = APIRouter()


@router.get("/status", response_model=KanjiTrainerStatus)
async def read_status(session: AsyncSession = Depends(get_session)) -> KanjiTrainerStatus:
    config = await load_runtime_config(session)
    url = config.kanji_trainer_mcp_url

    try:
        summary = await kanji_trainer.get_learning_summary(url, fresh=True)
    except kanji_trainer.KanjiTrainerUnavailable as exc:
        return KanjiTrainerStatus(reachable=False, url=url, error=str(exc))

    # The only "known" counts `get_learning_summary` carries that apply
    # `is_known`'s threshold rather than just the literal `known` state --
    # see `JlptLevelCounts` -- so this is what "one call, not the full
    # lists" (the brief) has to work with. It is scoped to subjects with an
    # assigned JLPT level, same as the `jlpt` breakdown itself.
    known_kanji = sum(level.kanji.known for level in summary.jlpt.values())
    known_vocabulary = sum(level.vocabulary.known for level in summary.jlpt.values())

    return KanjiTrainerStatus(
        reachable=True,
        url=url,
        level=summary.current_level,
        known_kanji=known_kanji,
        known_vocabulary=known_vocabulary,
    )
