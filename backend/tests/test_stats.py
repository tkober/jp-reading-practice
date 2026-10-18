"""History/Stats/Export API (issue #12): `GET /api/history`, `GET
/api/stats`, `GET /api/export`.

Rows are built directly against the ORM (`GeneratedText`/`ReadingSession`/
`HelpEvent`/`ChatMessage`), not through the reading-session flow itself --
these endpoints read history that already exists, so the point here is
controlling exactly which `finished_at`/`active_ms`/`answers` land in the
database, not re-exercising `api/sessions.py` (that is `test_sessions.py`'s
job). The actual statistics maths is unit tested without a database at all
in `test_stats_math.py`; this file is about the queries wiring real rows
into that maths and back out as JSON.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ChatMessage, GeneratedText, HelpEvent, ReadingSession, Topic

NOW = datetime.now(timezone.utc)


def _analysis(
    *, characters: int = 300, words: int = 100, jlpt_mix: dict | None = None, tokens: list | None = None
) -> dict:
    return {
        "paragraphs": [{"tokens": tokens or []}],
        "metrics": {
            "characters": characters,
            "words": words,
            "kanji_total": 0,
            "kanji_unknown": 0,
            "unknown_kanji_share": 0.0,
            "jlpt_mix": jlpt_mix or {"n5": 1.0, "n4": 0.0, "n3": 0.0, "n2": 0.0, "n1": 0.0, "unlisted": 0.0},
        },
    }


async def _create_text(
    session: AsyncSession,
    *,
    title: str = "テスト",
    topic_id: int | None = None,
    topic_slug: str = "daily-life",
    style: str = "casual",
    length: str = "short",
    characters: int = 300,
    words: int = 100,
    jlpt_mix: dict | None = None,
    tokens: list | None = None,
    questions: list | None = None,
) -> GeneratedText:
    row = GeneratedText(
        topic_id=topic_id,
        params={
            "topic_slug": topic_slug,
            "length": length,
            "preset": "easy",
            "unknown_kanji_target": 0.02,
            "jlpt_mix": {},
            "style": style,
        },
        title=title,
        body="テスト" * 10,
        questions=questions
        if questions is not None
        else [{"question": "Q1", "options": ["A", "B"], "answer_index": 0}],
        analysis=_analysis(characters=characters, words=words, jlpt_mix=jlpt_mix, tokens=tokens),
        known_snapshot={"level": None, "known_kanji_count": 0, "known_vocabulary_count": 0, "kanji_trainer_error": None},
        model="gpt-4o-mini",
        usage=[],
        cost_usd=None,
        attempts=1,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _create_session(
    session: AsyncSession,
    text_row: GeneratedText,
    *,
    status: str = "finished",
    active_ms: int = 60_000,
    answers: list | None = None,
    comprehension_correct: int | None = 1,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> ReadingSession:
    row = ReadingSession(
        text_id=text_row.id,
        status=status,
        started_at=started_at or NOW,
        active_ms=active_ms,
        answers=answers if answers is not None else [0],
        comprehension_correct=comprehension_correct if status == "finished" else None,
        finished_at=finished_at or (NOW if status == "finished" else None),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _log_help(
    session: AsyncSession,
    session_row: ReadingSession,
    *,
    kind: str = "word_lookup",
    target: str,
    token_id: str = "0-0",
    lemma: str,
    surface: str | None = None,
    weight: int = 1,
) -> HelpEvent:
    row = HelpEvent(
        session_id=session_row.id,
        kind=kind,
        target=target,
        token_id=token_id,
        lemma=lemma,
        surface=surface or lemma,
        weight=weight,
        at_ms=0,
        cost_usd=None,
    )
    session.add(row)
    await session.commit()
    return row


# --- history ------------------------------------------------------------------


async def test_history_oldest_first_with_unfinished_rows_nulled(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(session, characters=600, words=100)
    oldest = await _create_session(
        session, text, started_at=NOW - timedelta(days=2), finished_at=NOW - timedelta(days=2),
        active_ms=5 * 60_000, comprehension_correct=1,
    )
    newest_unfinished = await _create_session(
        session, text, status="reading", started_at=NOW - timedelta(days=1)
    )

    response = await client.get("/api/history")
    assert response.status_code == 200
    body = response.json()

    assert [entry["id"] for entry in body] == [oldest.id, newest_unfinished.id]

    finished_entry = body[0]
    assert finished_entry["finished"] is True
    assert finished_entry["speed_chars_per_minute"] == 120  # 600 chars / 5 min
    assert finished_entry["comprehension_correct"] == 1
    assert finished_entry["comprehension_total"] == 1

    unfinished_entry = body[1]
    assert unfinished_entry["finished"] is False
    assert unfinished_entry["speed_chars_per_minute"] is None
    assert unfinished_entry["helps_per_100_words"] is None
    assert unfinished_entry["comprehension_correct"] is None


async def test_history_topic_name_falls_back_to_slug_when_topic_deleted(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(session, topic_id=None, topic_slug="current-events")
    await _create_session(session, text)

    response = await client.get("/api/history")
    assert response.json()[0]["topic_name"] == "Current events"


# --- stats: empty state --------------------------------------------------------


async def test_stats_empty_under_three_finished_sessions(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(session)
    await _create_session(session, text)
    await _create_session(session, text)  # only 2 finished

    response = await client.get("/api/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] is None
    assert body["speed_series"] == []
    assert body["problem_words"] == []


# --- stats: summary numbers -----------------------------------------------------


async def test_stats_summary_speed_and_comprehension(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(session, characters=600, words=100)
    # Three sessions, 5/6/10 minutes active -> 120/100/60 chars-per-minute.
    for minutes, correct in ((5, 1), (6, 1), (10, 0)):
        await _create_session(
            session, text, active_ms=minutes * 60_000, comprehension_correct=correct,
            started_at=NOW, finished_at=NOW,
        )

    response = await client.get("/api/stats")
    body = response.json()
    summary = body["summary"]
    assert summary is not None
    # median(120, 100, 60) = 100
    assert summary["speed_chars_per_minute"] == 100
    # pooled comprehension: 2 correct / 3 total = 66.7%
    assert summary["comprehension_percent"] == pytest.approx(66.7)


async def test_stats_speed_delta_percent(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(session, characters=600, words=100)
    # Recent window (last 30 days): 5 min -> 120 chars/min.
    await _create_session(
        session, text, active_ms=5 * 60_000,
        started_at=NOW - timedelta(days=5), finished_at=NOW - timedelta(days=5),
    )
    # Prior window (30-60 days ago): 10 min -> 60 chars/min.
    await _create_session(
        session, text, active_ms=10 * 60_000,
        started_at=NOW - timedelta(days=40), finished_at=NOW - timedelta(days=40),
    )
    await _create_session(
        session, text, active_ms=10 * 60_000,
        started_at=NOW - timedelta(days=45), finished_at=NOW - timedelta(days=45),
    )

    response = await client.get("/api/stats")
    delta = response.json()["summary"]["speed_delta_percent"]
    # recent mean 120, prior mean 60 -> +100%.
    assert delta == 100.0


async def test_stats_speed_by_style_and_topic(
    client: AsyncClient, session: AsyncSession
) -> None:
    casual_text = await _create_text(
        session, characters=600, words=100, style="casual", topic_slug="travel"
    )
    formal_text = await _create_text(
        session, characters=300, words=100, style="formal", topic_slug="history"
    )
    await _create_session(session, casual_text, active_ms=5 * 60_000)  # 120 chars/min
    await _create_session(session, formal_text, active_ms=5 * 60_000)  # 60 chars/min
    await _create_session(session, formal_text, active_ms=5 * 60_000)

    response = await client.get("/api/stats")
    body = response.json()
    by_style = {bar["label"]: bar["value"] for bar in body["speed_by_style"]}
    assert by_style == {"Casual": 120, "Formal": 60}

    by_topic = {bar["label"]: bar["value"] for bar in body["speed_by_topic"]}
    assert by_topic == {"Travel": 120, "History": 60}


# --- stats: reading level -------------------------------------------------------


async def test_stats_reading_level_comfortable(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(
        session, characters=600, words=100, jlpt_mix={"n5": 0.5, "n4": 0.5, "n3": 0.0, "n2": 0.0, "n1": 0.0}
    )
    for _ in range(5):
        await _create_session(
            session, text, active_ms=5 * 60_000, comprehension_correct=1,
        )

    response = await client.get("/api/stats")
    summary = response.json()["summary"]
    assert summary["reading_level"] == "N4"
    assert summary["reading_level_detail"] == "comfortable"


async def test_stats_reading_level_with_help(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(
        session, characters=600, words=100, jlpt_mix={"n5": 0.5, "n4": 0.5, "n3": 0.0, "n2": 0.0, "n1": 0.0}
    )
    for _ in range(5):
        session_row = await _create_session(
            session, text, active_ms=5 * 60_000, comprehension_correct=1,
        )
        # Several distinct helps -- weight sum high enough to push helps/100
        # words above the comfortable threshold.
        for i in range(8):
            await _log_help(
                session, session_row, target=f"word{i}", lemma=f"word{i}", kind="word_lookup"
            )

    response = await client.get("/api/stats")
    summary = response.json()["summary"]
    assert summary["reading_level"] == "—"
    assert summary["reading_level_detail"] == "with help at N4"


async def test_stats_reading_level_none_yet(
    client: AsyncClient, session: AsyncSession
) -> None:
    text = await _create_text(session, characters=600, words=100)  # defaults to N5
    # Only 2 sessions at N5 -- below the per-level minimum of 3.
    await _create_session(session, text, active_ms=5 * 60_000)
    await _create_session(session, text, active_ms=5 * 60_000)
    # A different level (N1), so the 3rd finished session overall does not
    # also land in N5's sample.
    extra_text = await _create_text(
        session, characters=300, words=100,
        jlpt_mix={"n5": 0.0, "n4": 0.0, "n3": 0.0, "n2": 0.0, "n1": 1.0},
    )
    await _create_session(session, extra_text, active_ms=5 * 60_000)

    response = await client.get("/api/stats")
    summary = response.json()["summary"]
    assert summary["reading_level"] == "—"
    assert summary["reading_level_detail"] == "not enough sessions per level yet"


# --- stats: problem words -------------------------------------------------------


async def test_stats_problem_words_across_texts(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = {"id": "0-0", "surface": "食べました", "lemma": "食べる", "reading": "たべました", "lemma_reading": "たべる", "is_word": True}
    text_a = await _create_text(session, tokens=[token])
    text_b = await _create_text(session, tokens=[token])
    text_c = await _create_text(session)  # lemma never looked up here

    session_a = await _create_session(session, text_a, active_ms=5 * 60_000)
    session_b = await _create_session(session, text_b, active_ms=5 * 60_000)
    session_c = await _create_session(session, text_c, active_ms=5 * 60_000)

    await _log_help(session, session_a, target="食べる", lemma="食べる", token_id="0-0")
    await _log_help(session, session_b, target="食べる", lemma="食べる", kind="explain", token_id="0-0")
    await _log_help(session, session_c, target="other", lemma="other", token_id="0-0")

    response = await client.get("/api/stats")
    problem_words = response.json()["problem_words"]
    assert len(problem_words) == 1
    assert problem_words[0]["word"] == "食べる"
    assert problem_words[0]["reading"] == "たべる"
    assert problem_words[0]["times_looked_up"] == 2


# --- export ----------------------------------------------------------------------


async def test_export_shape(client: AsyncClient, session: AsyncSession) -> None:
    topic = Topic(
        slug="export-test-topic", title="Export test", glyph="日", prompt="p", default_style="casual",
        feed_urls=[], is_builtin=False, sort_order=0,
    )
    session.add(topic)
    await session.commit()
    await session.refresh(topic)

    text = await _create_text(
        session, topic_id=topic.id,
        questions=[{"question": "Q1", "options": ["A", "B"], "answer_index": 1}],
    )
    session_row = await _create_session(session, text, active_ms=60_000)
    await _log_help(session, session_row, target="word", lemma="word")
    chat = ChatMessage(session_id=session_row.id, role="user", content="質問")
    session.add(chat)
    await session.commit()

    response = await client.get("/api/export")
    assert response.status_code == 200
    body = response.json()

    assert any(t["slug"] == "export-test-topic" for t in body["topics"])
    assert body["texts"][0]["questions"][0]["answer_index"] == 1
    assert body["sessions"][0]["id"] == session_row.id
    assert body["help_events"][0]["lemma"] == "word"
    assert body["chat_messages"][0]["content"] == "質問"
