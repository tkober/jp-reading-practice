"""HTTP routes, mounted under /api by :mod:`app.main`."""

from __future__ import annotations

from fastapi import APIRouter

from . import health, settings

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(settings.router, prefix="/settings", tags=["settings"])

__all__ = ["router"]
