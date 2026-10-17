"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    """Runtime configuration for the backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    # Same default as jp-conversation-practice's analysis slot: fast and cheap,
    # and this slot's job (producing the reading texts) is the same shape of
    # work -- a chat completion, not a live conversation.
    generation_model: str = "gpt-4o-mini"
    # Same default as jp-conversation-practice's scenario-assistant slot: that
    # slot also writes prose rather than driving a live exchange, which is
    # worth a stronger model.
    help_model: str = "gpt-4o"
    # Where the built-in topics' Markdown files live -- see topic_files.py.
    topics_dir: str = "topics"

    # --- Kanji Trainer MCP ---
    # Where the known-vocabulary source lives, for the MCP client that lands
    # with a later issue (out of scope here). 8086 is kanji-trainer's own port.
    kanji_trainer_mcp_url: str = "http://localhost:8086/mcp"

    # --- Features ---
    # Off by default until the MCP client and the generation prompt that would
    # use it exist -- see REQUIREMENTS.md's open questions.
    web_search_enabled: bool = False

    # --- Database ---
    # Postgres only -- no SQLite variant, unlike the sibling apps (decided for
    # this app). DB_URL carries only host/port/database; credentials come per
    # role, the same split the other stacks on postgres-core use. The owner
    # role runs DDL at startup, the app role serves every request.
    db_url: str = "postgresql://localhost:5432/jp_reading_practice"
    db_user: str = "jp_reading_practice_app"
    db_password: str = ""
    db_owner_user: str = "jp_reading_practice_owner"
    db_owner_password: str = ""
    # postgres-core lives in its own compose stack, so `depends_on` cannot
    # order this one after it. On a host reboot both come up at once and the
    # database may not accept connections for a while yet.
    db_connect_attempts: int = 30
    db_connect_delay_seconds: float = 2.0

    # --- Server ---
    cors_origins: str = "http://localhost:4200"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def _role_url(self, user: str, password: str) -> URL:
        """Build an async SQLAlchemy URL for one role from the base DB_URL."""
        url = make_url(self.db_url)
        return url.set(
            drivername="postgresql+asyncpg",
            username=user or None,
            password=password or None,
        )

    @property
    def app_database_url(self) -> URL:
        """The role serving requests -- CRUD only, no DDL."""
        return self._role_url(self.db_user, self.db_password)

    @property
    def owner_database_url(self) -> URL:
        """The role used at startup for DDL and seeding."""
        return self._role_url(self.db_owner_user, self.db_owner_password)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()
