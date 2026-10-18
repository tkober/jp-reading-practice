"""DB glue for Stretch's adaptive difficulty (issue #13) -- the only module
that touches `stretch_adjustments` directly. Every actual decision (what a
difficulty resolves to, which way a session should move it) lives in the
pure `app.stretch`; this module is only the queries around it, same split as
`app.helps`/`api/sessions.py`'s per-session weight sum, or `stats_math.py`/
`api/stats.py`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import stretch
from .db import StretchAdjustment


async def latest_adjustment(session: AsyncSession) -> StretchAdjustment | None:
    """The most recent adjustment ever recorded, across every session --
    `None` before the first one. Ordered by `id` (insertion order), not
    `created_at`: two rows could in principle share a timestamp, never an
    insertion order."""
    return await session.scalar(
        select(StretchAdjustment).order_by(StretchAdjustment.id.desc()).limit(1)
    )


async def current_d(session: AsyncSession) -> float:
    """Stretch's current difficulty: the latest adjustment's `d_after`, or
    `stretch.D_START` when none has ever run yet (brief: "Current d = latest
    row's d_after, else 1.0")."""
    row = await latest_adjustment(session)
    return row.d_after if row is not None else stretch.D_START


async def record_adjustment(
    session: AsyncSession,
    *,
    reading_session_id: int,
    d_before: float,
    d_after: float,
    helps_per_100_words: float,
    comprehension: float,
    reason: str,
) -> bool:
    """Insert one `stretch_adjustments` row, deduped by `session_id` (the
    table's own unique constraint) -- idempotent per session, the same
    `ON CONFLICT DO NOTHING` convention `help_events` uses elsewhere in this
    app (see `api/sessions.py`'s `_log_help`). Returns whether a row was
    actually inserted; the one caller (`api/sessions.py`'s `answer_question`)
    only ever reaches this once a session's status flips to `finished`,
    which happens exactly once per session, so a `False` here would mean
    that invariant broke, not a real race to handle."""
    stmt = (
        postgresql_insert(StretchAdjustment)
        .values(
            session_id=reading_session_id,
            d_before=d_before,
            d_after=d_after,
            helps_per_100_words=helps_per_100_words,
            comprehension=comprehension,
            reason=reason,
        )
        .on_conflict_do_nothing(index_elements=["session_id"])
    )
    result = await session.execute(stmt)
    return result.rowcount > 0
