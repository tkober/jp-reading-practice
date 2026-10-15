"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    database: bool


# --- Settings ----------------------------------------------------------------


class SettingsIn(BaseModel):
    """Patch for the settings row.

    Every field is optional: omitting one leaves it unchanged. Sending an
    empty string (or ``null``) clears the override so the environment default
    applies again.
    """

    openai_api_key: str | None = None
    generation_model: str | None = None
    help_model: str | None = None
    kanji_trainer_mcp_url: str | None = None
    web_search_enabled: bool | None = None


class SettingsOut(BaseModel):
    """The effective settings, safe to send to the browser.

    The OpenAI key is never returned in full -- only whether one is set, a
    masked hint, and whether it came from the environment.
    """

    generation_model: str
    help_model: str
    kanji_trainer_mcp_url: str
    web_search_enabled: bool

    openai_api_key_set: bool
    openai_api_key_hint: str | None = None
    openai_api_key_from_env: bool


# --- Kanji Trainer MCP ---------------------------------------------------


class KanjiTrainerStatus(BaseModel):
    """What the Settings screen's "Test connection" button shows.

    Always HTTP 200 -- this reports the connection's state, it is not itself
    failing when kanji-trainer is unreachable. `level`/`known_kanji`/
    `known_vocabulary` are `None` exactly when `reachable` is `False`.
    """

    reachable: bool
    url: str
    level: int | None = None
    known_kanji: int | None = None
    known_vocabulary: int | None = None
    error: str | None = None
