"""Test fixtures.

No Docker in this environment, so ``TEST_DB_URL`` (e.g.
``postgresql://dev@localhost:5432/postgres``) points the suite at a local
Postgres superuser connection, which this fixture uses to create a throwaway
database (``jp_reading_practice_test``) plus the owner/app roles for the run
-- exactly like the deployment bootstrap would (``dev/initdb/01-roles.sql``)
-- and drops everything again afterwards. Without ``TEST_DB_URL``, the suite
falls back to testcontainers, like kanji-trainer's.

HTTP tests go through ``httpx.ASGITransport`` rather than ``TestClient``: the
latter runs the app on its own event loop in a worker thread, which the shared
SQLAlchemy engine cannot be used from.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
import pytest_asyncio

DB_NAME = "jp_reading_practice_test"
OWNER = "jp_reading_practice_owner"
APP = "jp_reading_practice_app"
PASSWORD = "testing"


@pytest.fixture(scope="session", autouse=True)
def database_url() -> Iterator[str]:
    """Point the process at a throwaway database for the whole run."""
    test_db_url = os.environ.get("TEST_DB_URL")
    if test_db_url:
        yield from _local_postgres(test_db_url)
        return

    try:
        # Moved in testcontainers 4.14; the old path still works but warns.
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - older testcontainers
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17", dbname=DB_NAME) as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        _bootstrap_roles(dsn)
        url = (
            f"postgresql://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(5432)}/{DB_NAME}"
        )
        _apply_env(url)
        yield url


def _local_postgres(test_db_url: str) -> Iterator[str]:
    """Create a throwaway database plus roles against a local superuser
    connection, and drop everything again when the run ends."""
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        conn.execute(f"CREATE DATABASE {DB_NAME}")

    db_dsn = _with_database(test_db_url, DB_NAME)
    _bootstrap_roles(db_dsn)

    url = _with_database(test_db_url, DB_NAME)
    _apply_env(url)
    try:
        yield url
    finally:
        with psycopg.connect(test_db_url, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()"
            )
            conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
            conn.execute(f"DROP ROLE IF EXISTS {OWNER}")
            conn.execute(f"DROP ROLE IF EXISTS {APP}")


def _with_database(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _bootstrap_roles(dsn: str) -> None:
    """Create the two roles the app expects and grant them exactly like the
    deployment bootstrap (``dev/initdb/01-roles.sql``) does."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"DROP ROLE IF EXISTS {OWNER}")
        conn.execute(f"DROP ROLE IF EXISTS {APP}")
        conn.execute(f"CREATE ROLE {OWNER} WITH LOGIN PASSWORD '{PASSWORD}'")
        conn.execute(f"CREATE ROLE {APP} WITH LOGIN PASSWORD '{PASSWORD}'")
        conn.execute(f"GRANT CONNECT ON DATABASE {DB_NAME} TO {APP}")
        conn.execute(f"ALTER SCHEMA public OWNER TO {OWNER}")
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {APP}")
        # The app role's table access comes from the owner's default
        # privileges, exactly as the deployment's bootstrap SQL sets it up --
        # no GRANT is ever issued from application code.
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER} IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP}"
        )
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER} IN SCHEMA public "
            f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {APP}"
        )


def _apply_env(url: str) -> None:
    os.environ["DB_URL"] = url
    os.environ["DB_OWNER_USER"] = OWNER
    os.environ["DB_OWNER_PASSWORD"] = PASSWORD
    os.environ["DB_USER"] = APP
    os.environ["DB_PASSWORD"] = PASSWORD
    os.environ["OPENAI_API_KEY"] = ""

    from app.config import get_settings

    get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def fresh_schema(database_url: str) -> AsyncIterator[None]:
    """Drop and recreate the schema around every test."""
    from sqlalchemy import text

    from app.config import get_settings
    from app.db import Base, _new_engine, init_db, reset_engines

    await reset_engines()
    engine = _new_engine(get_settings().owner_database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # Base.metadata knows nothing about Alembic's own bookkeeping table,
        # so it survives drop_all -- leaving it around would make every test
        # look like an already-migrated database instead of a fresh one, and
        # skip exactly the code path test_migrations.py exists to guard.
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()

    await init_db()
    yield
    await reset_engines()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[object]:
    from app.db import get_sessionmaker

    async with get_sessionmaker()() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[object]:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
