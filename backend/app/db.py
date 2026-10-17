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
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
from .topic_files import load_topic_files

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


class Topic(Base):
    """A domain the learner can generate reading texts about (issue #8).

    ``title`` and ``prompt`` are English -- ``prompt`` is model-facing (it is
    framed as a domain inside `prompts.py`'s fixed generation frame, never
    instructions that can override it, same lesson as jp-conversation-
    practice's scenarios); ``glyph`` is the short Japanese word/kanji shown
    on the topic tile (e.g. 旅行). Seeded from ``backend/topics/*.md`` at
    startup (``seed_topics``) -- a topic the user has edited
    (``is_customized``) keeps its wording across a redeploy, exactly like
    jp-conversation-practice's ``Scenario``/``seed_scenarios``.

    ``feed_urls`` is a JSON list of RSS feed URLs, used by #15's current-
    events generation -- unused by anything in this issue beyond storage and
    the editor's UI for it.
    """

    __tablename__ = "topics"
    __table_args__ = (Index("idx_topics_sort", "sort_order", "title"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    glyph: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    default_style: Mapped[str] = mapped_column(String, nullable=False, server_default="casual")
    feed_urls: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    is_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GeneratedText(Base):
    """One generated reading text (issue #8).

    Named ``GeneratedText`` rather than ``Text`` purely to avoid shadowing
    ``sqlalchemy.Text`` (the column type) in this module -- the table itself
    is ``texts``, per the brief.

    ``topic_id`` is nullable with ``ON DELETE SET NULL``: deleting a custom
    topic must not delete the texts generated from it, it only loses the
    link (the topic slug/title travel inside ``params`` for that reason,
    so a text stays self-describing even once its topic is gone, or for the
    "surprise me" case which never had one).

    ``params`` records what was *asked for* (topic slug, length target,
    preset, unknown-kanji target, JLPT mix target, style); ``analysis`` is
    the full `TextAnalysis` (tokens + metrics) as of generation, used to
    render the reading screen without re-tokenising; ``known_snapshot`` is
    deliberately smaller than the known set itself -- counts and the
    learner's level, not the full kanji/vocabulary lists, which would bloat
    every row for data `analyze()` already reduced into the metrics above.
    ``usage``/``cost_usd`` are per the generation call(s) -- see
    `generation.py` and `pricing.py`.
    """

    __tablename__ = "texts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    questions: Mapped[list] = mapped_column(JSONB, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSONB, nullable=False)
    known_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    usage: Mapped[list] = mapped_column(JSONB, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReadingSession(Base):
    """One reading session for a generated text (issue #9).

    Reading a text again (`POST /api/sessions` with the same `text_id`)
    always starts a new row -- a session is one attempt, not a resumable
    slot shared across attempts. `status` walks `reading -> questions ->
    finished`, driven entirely by `api/sessions.py`. `active_ms`/`paused_ms`
    are the heartbeat's own running totals (monotonic -- a heartbeat only
    ever raises them, never lowers them); `answers` is one entry per
    question (the chosen option index, or `None` while unanswered), index-
    aligned with the text's own `questions`. `comprehension_correct` is
    `None` until `finished`, then the number of questions answered
    correctly (stats read it without re-checking every answer).
    """

    __tablename__ = "reading_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_id: Mapped[int] = mapped_column(
        ForeignKey("texts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="reading")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reading_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    paused_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    answers: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    comprehension_correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HelpEvent(Base):
    """One costed help, logged once per target/session (issue #9, extended
    by #10).

    `kind` is a plain string column, not a DB enum, so #10 can add
    `explain`/`translate`/`grammar` (and a later `tutor`) without a schema
    change -- see `helps.py` for every weight. The unique constraint on
    `(session_id, kind, target)` is the dedupe itself: a repeat insert is a
    no-op (`ON CONFLICT DO NOTHING`, see `api/sessions.py`), and its weight
    is the "counted once per target per session" rule from the concept, not
    a second thing the code has to decide.

    `target` is what is actually deduped on: the lemma for a word-kind help
    (`reading_peek`, `word_lookup`, `explain`), the sentence key
    (`sentences.Sentence.key`, `"<paragraph>-<sentence>"`) for a sentence-kind
    help (`translate`, `grammar`) -- see `sentences.py` and the assist
    endpoint. `lemma`/`surface`/`token_id` still ride along unconditionally
    (not just for word kinds) so the summary can always join back to the
    exact occurrence that triggered the help, even one whose dedupe target is
    a sentence key rather than `lemma` itself.

    `cost_usd` is `NULL` for `reading_peek`/`word_lookup` (not an LLM call at
    all) and for an assist answer served from `help_answers`' cache (a cache
    hit costs this *session* nothing, even though the answer itself has a
    cost recorded against whichever session first generated it) -- `0.0`
    specifically marks "costed, but free this time" so summing cache hits
    with `NULL` reading-peeks the same way (both as 0) is correct. Only an
    assist that this session's own request actually generated carries the
    real amount. `api/sessions.py`'s summary's `assists_cost_usd` is the sum
    of this column over one session.
    """

    __tablename__ = "help_events"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "kind", "target", name="uq_help_events_session_kind_target"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("reading_sessions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)
    token_id: Mapped[str] = mapped_column(String, nullable=False)
    lemma: Mapped[str] = mapped_column(String, nullable=False)
    surface: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    #: `ReadingSession.active_ms` at the moment this help was logged.
    at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    #: See the class docstring -- `NULL` for a non-LLM help, `0.0` for an
    #: assist answer served from cache, the real cost for one this session
    #: generated itself.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HelpAnswer(Base):
    """One cached LLM answer for one target in one text (issue #10).

    The cache itself: the unique constraint on `(text_id, kind, target)`
    means the same question about the same text is answered once ever,
    reused by *any* later session that asks it again -- unlike `HelpEvent`,
    which is scoped to one session's own dedupe/weight bookkeeping, this
    table does not know or care which session asked. `target` is the same
    lemma/sentence-key `HelpEvent.target` uses for the matching kind (see its
    docstring and `sentences.py`).

    `model`/`usage`/`cost_usd` describe the one generation call that produced
    `answer` -- `cost_usd` is `NULL` exactly when `pricing.rates_for()` does
    not know `model`, same convention as `GeneratedText.cost_usd`.
    """

    __tablename__ = "help_answers"
    __table_args__ = (
        UniqueConstraint(
            "text_id", "kind", "target", name="uq_help_answers_text_kind_target"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_id: Mapped[int] = mapped_column(
        ForeignKey("texts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
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
            await seed_topics(session)
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


async def seed_topics(session: AsyncSession) -> None:
    """Insert the Markdown-defined topics, refreshing the untouched ones.

    Same shape as jp-conversation-practice's ``seed_scenarios``: a topic the
    user has edited (``is_customized``) keeps its wording -- the upsert
    deliberately skips those rows rather than restoring the file text.
    """
    files = load_topic_files()
    if not files:
        log.warning("No topic files found; starting without built-in topics")
        return

    for index, entry in enumerate(files):
        stmt = postgresql_insert(Topic).values(
            slug=entry.slug,
            title=entry.title,
            glyph=entry.glyph,
            prompt=entry.prompt,
            default_style=entry.default_style,
            feed_urls=entry.feed_urls,
            is_builtin=True,
            sort_order=index,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Topic.slug],
                set_={
                    "title": stmt.excluded.title,
                    "glyph": stmt.excluded.glyph,
                    "prompt": stmt.excluded.prompt,
                    "default_style": stmt.excluded.default_style,
                    "feed_urls": stmt.excluded.feed_urls,
                    "sort_order": stmt.excluded.sort_order,
                    "updated_at": func.now(),
                },
                where=Topic.is_customized.is_(False),
            )
        )

    log.info("Seeded %d built-in topic(s)", len(files))
