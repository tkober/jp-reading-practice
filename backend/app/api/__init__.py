"""HTTP routes, mounted under /api by :mod:`app.main`."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    analysis,
    health,
    kanji_trainer,
    presets,
    sessions,
    settings,
    stats,
    suggestions,
    texts,
    topics,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(settings.router, prefix="/settings", tags=["settings"])
router.include_router(kanji_trainer.router, prefix="/kanji-trainer", tags=["kanji-trainer"])
router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
router.include_router(topics.router, prefix="/topics", tags=["topics"])
router.include_router(texts.router, prefix="/texts", tags=["texts"])
router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
router.include_router(sessions.pace_router, prefix="/reading", tags=["sessions"])
router.include_router(stats.router, tags=["stats"])
router.include_router(presets.router, prefix="/presets", tags=["presets"])
router.include_router(suggestions.router, prefix="/suggestions", tags=["suggestions"])

__all__ = ["router"]
