"""The owner/app role split: only the owner may run DDL.

`fresh_schema` (conftest.py) already proves the app runs fine on the app
role for ordinary requests. This proves the other half: a stray DDL
statement in a request path cannot slip through, because the app role's
connection genuinely lacks the privilege -- it is not just that application
code never happens to issue one.
"""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy.engine import URL

from app.config import get_settings


def _plain_dsn(url: URL) -> str:
    """A bare ``postgresql://`` DSN psycopg's sync driver accepts directly --
    the app's own URLs carry the ``+psycopg`` SQLAlchemy dialect suffix."""
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def test_app_role_cannot_create_a_table() -> None:
    dsn = _plain_dsn(get_settings().app_database_url)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE TABLE should_not_exist (id integer)")


async def test_owner_role_can_create_a_table() -> None:
    """The negative result above is meaningful only if the owner role -- the
    one `init_db` actually uses for migrations -- can do what the app role
    cannot."""
    dsn = _plain_dsn(get_settings().owner_database_url)

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE TABLE owner_can_create_this (id integer)")
        conn.execute("DROP TABLE owner_can_create_this")
