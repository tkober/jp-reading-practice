"""The effective configuration for one request.

Two layers: the environment (``.env``) provides the defaults a fresh
deployment boots with, and the ``app_settings`` row overrides anything the
user changes in the Settings screen. A NULL column means "not set here", so
clearing a field in the UI falls back to the environment rather than blanking
the setting.

Loaded fresh per request instead of cached: the table has one row, and a
stale OpenAI key after a settings change would be far more annoying than the
lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import AppSettings, load_settings


@dataclass(frozen=True)
class RuntimeConfig:
    """Everything the app needs at runtime, with overrides already applied."""

    # --- user-editable ---
    openai_api_key: str
    generation_model: str
    help_model: str
    kanji_trainer_mcp_url: str
    web_search_enabled: bool

    # --- environment only (infrastructure, not user business) ---
    openai_api_base: str

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)


def _pick(override: str | None, fallback: str) -> str:
    """Prefer a non-empty database value, else the environment default."""
    value = (override or "").strip()
    return value or fallback


def build_runtime_config(row: AppSettings | None, env: Settings) -> RuntimeConfig:
    """Merge the settings row onto the environment defaults."""
    return RuntimeConfig(
        openai_api_key=_pick(row and row.openai_api_key, env.openai_api_key),
        generation_model=_pick(row and row.generation_model, env.generation_model),
        help_model=_pick(row and row.help_model, env.help_model),
        kanji_trainer_mcp_url=_pick(
            row and row.kanji_trainer_mcp_url, env.kanji_trainer_mcp_url
        ),
        web_search_enabled=(
            env.web_search_enabled
            if row is None or row.web_search_enabled is None
            else row.web_search_enabled
        ),
        openai_api_base=env.openai_api_base,
    )


async def load_runtime_config(session: AsyncSession) -> RuntimeConfig:
    """Read the settings row and merge it onto the environment."""
    return build_runtime_config(await load_settings(session), get_settings())
