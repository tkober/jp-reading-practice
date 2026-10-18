"""`GET /api/presets` (issue #13): easy/challenge are the static table
verbatim, stretch resolves at its current `d` plus the last adjustment's
own reason/date."""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis import analyze
from app.db import GeneratedText, ReadingSession, StretchAdjustment
from app.known_set import KnownSet


async def _finished_session(session: AsyncSession) -> int:
    """A minimal finished `reading_sessions` row -- `StretchAdjustment.
    session_id` is a real FK, so a test recording one needs a row to point
    at, even though its own content is irrelevant to these tests."""
    analysis = analyze("水を飲みます。", KnownSet(), {})
    text_row = GeneratedText(
        topic_id=None,
        params={"topic_slug": "daily-life", "length": "short", "preset": "stretch"},
        title="水",
        body="水を飲みます。",
        questions=[],
        analysis=analysis.model_dump(mode="json"),
        known_snapshot={},
        model="gpt-4o-mini",
        usage=[],
        attempts=1,
    )
    session.add(text_row)
    await session.commit()
    await session.refresh(text_row)

    session_row = ReadingSession(text_id=text_row.id, status="finished", answers=[])
    session.add(session_row)
    await session.commit()
    await session.refresh(session_row)
    return session_row.id


async def test_easy_and_challenge_are_the_static_presets(client: AsyncClient) -> None:
    response = await client.get("/api/presets")
    assert response.status_code == 200
    body = response.json()

    assert body["easy"]["unknown_kanji_target"] == pytest.approx(0.02)
    assert body["easy"]["jlpt_mix"]["n5"] == pytest.approx(0.70)
    assert body["challenge"]["unknown_kanji_target"] == pytest.approx(0.10)
    assert body["challenge"]["jlpt_mix"]["n2"] == pytest.approx(0.10)


async def test_stretch_defaults_to_d_1_with_no_adjustments(client: AsyncClient) -> None:
    response = await client.get("/api/presets")
    body = response.json()

    assert body["stretch"]["d"] == pytest.approx(1.0)
    assert body["stretch"]["unknown_kanji_target"] == pytest.approx(0.05)
    assert body["stretch"]["jlpt_mix"]["n3"] == pytest.approx(0.15)
    assert body["stretch"]["last_adjustment"] is None


async def test_stretch_reflects_the_latest_adjustment(
    client: AsyncClient, session: AsyncSession
) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    session_id_1 = await _finished_session(session)
    session_id_2 = await _finished_session(session)
    # Two rows for two different sessions -- the *later* one (by id) wins,
    # even though both share a timestamp here.
    session.add_all(
        [
            StretchAdjustment(
                session_id=session_id_1,
                d_before=1.0,
                d_after=1.1,
                helps_per_100_words=2.0,
                comprehension=90.0,
                reason="harder",
                created_at=now,
            ),
            StretchAdjustment(
                session_id=session_id_2,
                d_before=1.1,
                d_after=1.2,
                helps_per_100_words=2.5,
                comprehension=85.0,
                reason="harder",
                created_at=now,
            ),
        ]
    )
    await session.commit()

    response = await client.get("/api/presets")
    body = response.json()

    assert body["stretch"]["d"] == pytest.approx(1.2)
    # d=1.2 interpolates 20% of the way from anchor 1 (5%) to anchor 2
    # (10%): 5 + 0.2*5 = 6%.
    assert body["stretch"]["unknown_kanji_target"] == pytest.approx(0.06)
    assert body["stretch"]["last_adjustment"]["reason"] == "harder"


async def test_stretch_shows_an_unchanged_last_adjustment_too(
    client: AsyncClient, session: AsyncSession
) -> None:
    session_id = await _finished_session(session)
    session.add(
        StretchAdjustment(
            session_id=session_id,
            d_before=1.0,
            d_after=1.0,
            helps_per_100_words=5.0,
            comprehension=70.0,
            reason="unchanged",
        )
    )
    await session.commit()

    response = await client.get("/api/presets")
    body = response.json()

    assert body["stretch"]["d"] == pytest.approx(1.0)
    assert body["stretch"]["last_adjustment"]["reason"] == "unchanged"
