"""Persistence: ORM models, engine and schema management.

Single-user application, so ``app_settings`` holds exactly one row (id = 1).

Postgres only -- no SQLite variant, unlike kanji-trainer and
jp-conversation-practice (decided for this app). Two roles are used (see
:mod:`app.config`): the *owner* role runs DDL at startup, the *app* role
serves every request. The app role's access to the owner-created tables comes
from server-side ``ALTER DEFAULT PRIVILEGES`` (``dev/initdb/01-roles.sql``,
and the deployment bootstrap SQL that issue #4 will add), so no GRANT is
issued here.

This app starts from nothing, so there is no pre-Alembic database to bridge --
unlike kanji-trainer's ``_migrate_to_head`` / ``migrate_schema`` /
``ADDED_COLUMNS``, ``init_db`` here just runs ``alembic upgrade head``
straight away. Add that bridge back only if a release ever ships before
Alembic does, which is not the case yet.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import get_settings

log = logging.getLogger(__name__)

SETTINGS_ROW_ID = 1

# Errors that will never resolve by waiting: the roles, the password or the
# database itself are wrong, so retrying only delays a clear failure.
FATAL_SQLSTATES = {
    # Postgres deliberately reports a missing role and a wrong password with
    # the same code, so that an attacker cannot enumerate users. The message
    # has to name both causes -- claiming only "wrong password" sends someone
    # looking for a role that was never created.
    "28P01": (
        "authentication as {user} failed. Either the role does not exist, or its "
        "password differs from DB_OWNER_PASSWORD -- Postgres reports both the "
        "same way. Run dev/initdb/01-roles.sql (or the deployment bootstrap SQL) "
        "to create it."
    ),
    "28000": (
        "role {user} does not exist. Run dev/initdb/01-roles.sql (or the "
        "deployment bootstrap SQL)."
    ),
    "3D000": (
        "database {database} does not exist. Create it before starting the app."
    ),
}


class DatabaseUnavailable(RuntimeError):
    """The database could not be used, with a reason worth reading."""


def _fatal_reason(exc: BaseException) -> str | None:
    """Return a human explanation when the error cannot be fixed by waiting."""
    seen: list[BaseException | None] = [exc, getattr(exc, "orig", None), exc.__cause__]
    for candidate in seen:
        code = getattr(candidate, "sqlstate", None)
        if code in FATAL_SQLSTATES:
            settings = get_settings()
            return FATAL_SQLSTATES[code].format(
                user=settings.db_owner_user, database=settings.owner_database_url.database
            )
    return None


class Base(DeclarativeBase):
    pass


class AppSettings(Base):
    """User-editable configuration, exactly one row.

    Every column is nullable: a NULL means "not configured here", and the
    corresponding environment variable is used instead. That keeps a fresh
    deployment working from its .env alone while letting the Settings screen
    override anything without a redeploy.
    """

    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="app_settings_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)

    openai_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # Separate from `generation_model`: it answers a reading-help question
    # about a text already on screen rather than writing one from scratch,
    # modelled on jp-conversation-practice's `scenario_assistant_model` slot.
    help_model: Mapped[str | None] = mapped_column(String, nullable=True)
    kanji_trainer_mcp_url: Mapped[str | None] = mapped_column(String, nullable=True)
    web_search_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- engine ------------------------------------------------------------------

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _new_engine(url: URL) -> AsyncEngine:
    return create_async_engine(url, future=True)


def get_engine() -> AsyncEngine:
    """The request-time engine (app role), created on first use."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = _new_engine(get_settings().app_database_url)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def reset_engines() -> None:
    """Drop the cached engine so the next use re-reads the configuration.

    Production never needs this; the tests do, because they point the process
    at a throwaway database between cases.
    """
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one app-role session per request."""
    async with get_sessionmaker()() as session:
        yield session


# --- schema ------------------------------------------------------------------


async def init_db() -> None:
    """Bring the schema to Alembic's head and ensure the settings row.

    DDL requires the owner role, so this opens a short-lived owner connection.
    """
    settings = get_settings()
    owner_engine = _new_engine(settings.owner_database_url)
    try:
        await _wait_for_database(owner_engine)
        async with owner_engine.begin() as conn:
            await conn.run_sync(_alembic_upgrade_head)
        async with async_sessionmaker(owner_engine, expire_on_commit=False)() as session:
            await ensure_settings_row(session)
            await session.commit()
    finally:
        await owner_engine.dispose()


def _alembic_config() -> AlembicConfig:
    """Alembic's config, with the script location resolved from this module's
    own path rather than from the process's working directory -- a deployed
    container need not `WORKDIR` into `backend/` for this to find
    `alembic.ini` and `alembic/`.
    """
    backend_root = Path(__file__).resolve().parent.parent
    config = AlembicConfig(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return config


def _alembic_upgrade_head(sync_conn: Any) -> None:
    """Runs on the connection `init_db` already opened (see the `run_sync`
    call site) rather than opening a second one -- `alembic/env.py` picks it
    up from `config.attributes["connection"]`.
    """
    config = _alembic_config()
    config.attributes["connection"] = sync_conn
    alembic_command.upgrade(config, "head")


async def _wait_for_database(engine: AsyncEngine) -> None:
    """Block until the database accepts a connection, or fail with a reason.

    Waiting is right for a database that is merely not up yet, and wrong for
    one that will never let us in: a bad password or a missing role stays bad,
    so those raise immediately with an explanation instead of a stack trace
    repeated once per restart.
    """
    settings = get_settings()
    attempts = max(1, settings.db_connect_attempts)

    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            if attempt > 1:
                log.info("Database reachable after %d attempts", attempt)
            return
        except Exception as exc:  # noqa: BLE001 - re-raised below unless retryable
            reason = _fatal_reason(exc)
            if reason is not None:
                log.error("Cannot use the database: %s.", reason)
                # `from None`: the driver traceback adds nothing to a message
                # that already says exactly what to change.
                raise DatabaseUnavailable(reason) from None

            if attempt == attempts:
                log.error(
                    "Database still unreachable after %d attempts (%.0fs)",
                    attempts,
                    attempts * settings.db_connect_delay_seconds,
                )
                raise

            log.warning(
                "Database not reachable yet (attempt %d/%d): %s", attempt, attempts, exc
            )
            await asyncio.sleep(settings.db_connect_delay_seconds)


async def ensure_settings_row(session: AsyncSession) -> None:
    await session.execute(
        postgresql_insert(AppSettings)
        .values(id=SETTINGS_ROW_ID)
        .on_conflict_do_nothing(index_elements=[AppSettings.id])
    )


async def load_settings(session: AsyncSession) -> AppSettings | None:
    """Read the single settings row, if it exists yet."""
    return await session.scalar(select(AppSettings).where(AppSettings.id == SETTINGS_ROW_ID))
