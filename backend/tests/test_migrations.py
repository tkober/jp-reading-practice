"""The Alembic guard: a model change without a matching revision fails here.

`fresh_schema` (conftest.py) already ran `init_db`, so the schema this test
compares against `Base.metadata` is the one every other test -- and every
real deployment -- actually runs on. `compare_metadata` is the same check
`alembic revision --autogenerate` uses to decide whether there is anything
left to generate.
"""

from __future__ import annotations

from app.config import get_settings
from app.db import Base, _new_engine


def _compare(sync_conn) -> list:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    context = MigrationContext.configure(sync_conn)
    return compare_metadata(context, Base.metadata)


async def test_migrated_schema_matches_the_models() -> None:
    engine = _new_engine(get_settings().owner_database_url)
    try:
        async with engine.connect() as conn:
            diffs = await conn.run_sync(_compare)
    finally:
        await engine.dispose()

    assert diffs == [], (
        "the schema Alembic produces differs from Base.metadata -- add a "
        f"revision for it: {diffs}"
    )
