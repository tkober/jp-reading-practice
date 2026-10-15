"""The Settings screen.

The OpenAI API key never leaves the backend. What the UI gets is whether one
is set, a hint of its last characters so the user can tell which key it is,
and whether it came from the environment -- which the UI needs in order to
explain why an env-provided key cannot be cleared from the screen. Masking and
the PUT semantics (an omitted field is untouched, an empty one clears the
override) follow jp-conversation-practice's ``/api/settings``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SETTINGS_ROW_ID, AppSettings, get_session, load_settings
from ..model_catalog import ModelCatalog, is_valid_model_id
from ..models import SettingsIn, SettingsOut
from ..runtime_config import load_runtime_config

router = APIRouter()

# Long-lived so the live model list stays cached between requests; the key is
# passed per call because it can change on this very screen.
_catalog = ModelCatalog()

#: How much of the key the hint shows. Enough to tell two keys apart, useless
#: to anyone who only sees the hint.
_HINT_CHARS = 4


def _hint(value: str) -> str | None:
    if not value:
        return None
    return f"…{value[-_HINT_CHARS:]}" if len(value) > _HINT_CHARS else "…"


async def _current(session: AsyncSession) -> SettingsOut:
    row = await load_settings(session)
    config = await load_runtime_config(session)
    env = get_settings()

    stored = ((row.openai_api_key if row else None) or "").strip()
    return SettingsOut(
        generation_model=config.generation_model,
        help_model=config.help_model,
        kanji_trainer_mcp_url=config.kanji_trainer_mcp_url,
        web_search_enabled=config.web_search_enabled,
        openai_api_key_set=bool(config.openai_api_key),
        openai_api_key_hint=_hint(config.openai_api_key),
        openai_api_key_from_env=not stored and bool(env.openai_api_key),
    )


@router.get("", response_model=SettingsOut)
async def read_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    return await _current(session)


@router.put("", response_model=SettingsOut)
async def write_settings(
    payload: SettingsIn, session: AsyncSession = Depends(get_session)
) -> SettingsOut:
    """Store the fields the request actually carried.

    A field left out is untouched; an empty string clears the column so the
    environment default applies again. Collapsing those two into one would
    make it impossible to remove an override once it is set.
    """
    values: dict[str, object] = {}
    fields = payload.model_dump(exclude_unset=True)

    if "openai_api_key" in fields:
        key = (fields["openai_api_key"] or "").strip()
        values["openai_api_key"] = key or None

    for name in ("generation_model", "help_model"):
        if name not in fields:
            continue
        value = fields[name]
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None and not is_valid_model_id(str(value)):
            # The dropdown's free-text escape hatch accepts any model name;
            # silently keeping the previous value is friendlier than a 422
            # here, same as jp-conversation-practice's settings PUT.
            continue
        values[name] = value

    if "kanji_trainer_mcp_url" in fields:
        value = fields["kanji_trainer_mcp_url"]
        values["kanji_trainer_mcp_url"] = (value or "").strip() or None

    if "web_search_enabled" in fields:
        values["web_search_enabled"] = fields["web_search_enabled"]

    if values:
        values["updated_at"] = datetime.now(timezone.utc)
        await session.execute(
            update(AppSettings).where(AppSettings.id == SETTINGS_ROW_ID).values(**values)
        )
        await session.commit()

    return await _current(session)


@router.get("/models")
async def read_models(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Dropdown contents for the two configurable model slots."""
    config = await load_runtime_config(session)
    catalog = await _catalog.build(config.openai_api_base, config.openai_api_key)
    return catalog.as_dict()
