"""HTTP routes, mounted under /api by :mod:`app.main`."""

from __future__ import annotations

from fastapi import APIRouter

from . import analysis, health, kanji_trainer, settings, texts, topics

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(settings.router, prefix="/settings", tags=["settings"])
router.include_router(kanji_trainer.router, prefix="/kanji-trainer", tags=["kanji-trainer"])
router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
router.include_router(topics.router, prefix="/topics", tags=["topics"])
router.include_router(texts.router, prefix="/texts", tags=["texts"])

__all__ = ["router"]
