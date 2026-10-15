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
        # Counted from the full lists, not from the summary: its `counts` hold
        # the literal `known` state only (no Guru threshold), and its `jlpt`
        # breakdown only covers subjects the JLPT snapshot lists. The lists
        # apply `is_known` to everything, and generation needs them anyway,
        # so this fresh fetch also warms the cache for the next text.
        known_kanji = await kanji_trainer.get_known_kanji(url, fresh=True)
        known_vocabulary = await kanji_trainer.get_known_vocabulary(url, fresh=True)
    except kanji_trainer.KanjiTrainerUnavailable as exc:
        return KanjiTrainerStatus(reachable=False, url=url, error=str(exc))

    return KanjiTrainerStatus(
        reachable=True,
        url=url,
        level=summary.current_level,
        known_kanji=len(known_kanji),
        known_vocabulary=len(known_vocabulary),
    )
