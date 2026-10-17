"""Reading session API (issue #9): every endpoint, dedupe, monotonic time,
answer-once, wrong-status 409s, summary maths, pace default vs history, and
a lookup with Kanji Trainer down (the fake MCP server from
`test_kanji_trainer.py`).

Text rows are created directly with `analyze()` (no OpenAI, same pattern as
`test_api_texts.py`'s `_fake_outcome`), since generation itself is out of
scope here.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import kanji_trainer as kt
from app.analysis import analyze
from app.db import GeneratedText, ReadingSession
from app.known_set import KnownSet
from tests.test_kanji_trainer import _build_app, _free_port, _running, _State

BODY = "水を飲みます。猫がいます。"
QUESTIONS = [
    {"question": "What did they drink?", "options": ["Water", "Tea", "Milk", "Juice"], "answer_index": 0},
    {"question": "What animal is there?", "options": ["Dog", "Cat", "Bird", "Fish"], "answer_index": 1},
]


async def _create_text(session: AsyncSession, *, body: str = BODY, questions=None) -> GeneratedText:
    text_analysis = analyze(body, KnownSet(), {})
    row = GeneratedText(
        topic_id=None,
        params={
            "topic_slug": "daily-life",
            "length": "short",
            "preset": "easy",
            "unknown_kanji_target": 0.02,
            "jlpt_mix": {},
            "style": "casual",
        },
        title="水曜日",
        body=body,
        questions=list(questions if questions is not None else QUESTIONS),
        analysis=text_analysis.model_dump(mode="json"),
        known_snapshot={
            "level": None,
            "known_kanji_count": 0,
            "known_vocabulary_count": 0,
            "kanji_trainer_error": None,
        },
        model="gpt-4o-mini",
        usage=[],
        cost_usd=None,
        attempts=1,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _token_id(text_row: GeneratedText, surface: str) -> str:
    for paragraph in text_row.analysis["paragraphs"]:
        for token in paragraph["tokens"]:
            if token["surface"] == surface:
                return token["id"]
    raise AssertionError(f"no token with surface {surface!r}")


@pytest.fixture(autouse=True)
def _clear_kanji_trainer_cache() -> None:
    kt.clear_cache()
    yield
    kt.clear_cache()


# --- create / get --------------------------------------------------------


async def test_create_session_starts_in_reading_with_null_answers(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)

    response = await client.post("/api/sessions", json={"text_id": text_row.id})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "reading"
    assert body["active_ms"] == 0
    assert body["paused_ms"] == 0
    assert body["answers"] == [{"option_index": None, "correct_index": None}] * 2
    assert body["text"]["id"] == text_row.id
    assert body["comprehension_correct"] is None


async def test_create_session_unknown_text_is_404(client: AsyncClient) -> None:
    response = await client.post("/api/sessions", json={"text_id": 999999})
    assert response.status_code == 404


async def test_reading_again_creates_a_new_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    first = await client.post("/api/sessions", json={"text_id": text_row.id})
    second = await client.post("/api/sessions", json={"text_id": text_row.id})
    assert first.json()["id"] != second.json()["id"]


async def test_get_session_unknown_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/sessions/999999")
    assert response.status_code == 404


# --- heartbeat -------------------------------------------------------------


async def test_heartbeat_is_monotonic(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]

    first = await client.put(
        f"/api/sessions/{session_id}/time", json={"active_ms": 5000, "paused_ms": 1000}
    )
    assert first.json() == {"active_ms": 5000, "paused_ms": 1000}

    # A lower snapshot (e.g. a stale/out-of-order request) must not claw time back.
    second = await client.put(
        f"/api/sessions/{session_id}/time", json={"active_ms": 2000, "paused_ms": 500}
    )
    assert second.json() == {"active_ms": 5000, "paused_ms": 1000}

    third = await client.put(
        f"/api/sessions/{session_id}/time", json={"active_ms": 9000, "paused_ms": 1500}
    )
    assert third.json() == {"active_ms": 9000, "paused_ms": 1500}


async def test_heartbeat_outside_reading_is_409(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 1000, "paused_ms": 0}
    )

    response = await client.put(
        f"/api/sessions/{session_id}/time", json={"active_ms": 2000, "paused_ms": 0}
    )
    assert response.status_code == 409


# --- helps (reading peeks) -------------------------------------------------


async def test_help_dedupes_per_word_per_session(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    token_id = _token_id(text_row, "水")

    first = await client.post(
        f"/api/sessions/{session_id}/helps", json={"kind": "reading_peek", "token_id": token_id}
    )
    assert first.json() == {"counted": True, "weight": 1}

    second = await client.post(
        f"/api/sessions/{session_id}/helps", json={"kind": "reading_peek", "token_id": token_id}
    )
    assert second.json() == {"counted": False, "weight": 1}


async def test_help_unknown_token_is_404(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]

    response = await client.post(
        f"/api/sessions/{session_id}/helps", json={"kind": "reading_peek", "token_id": "no-such-token"}
    )
    assert response.status_code == 404


# --- lookups ---------------------------------------------------------------


async def test_lookup_logs_word_lookup_and_returns_details(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    token_id = _token_id(text_row, "水")

    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})
        response = await client.post(f"/api/sessions/{session_id}/lookups", json={"token_id": token_id})

    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "水"
    assert body["lemma"] == "水"
    # The fake server's `lookup_items` always answers `srs_stage=9` (see
    # `_build_app` in `test_kanji_trainer.py`) -- stage 9 is "Burned".
    assert body["known_status"] == "Kanji Trainer: Burned"

    # A repeat lookup of the same word must still answer normally (only the
    # dedupe inside `help_events` is silent, not the lookup response).
    second = await client.post(f"/api/sessions/{session_id}/lookups", json={"token_id": token_id})
    assert second.status_code == 200


async def test_lookup_with_kanji_trainer_down_still_answers(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    token_id = _token_id(text_row, "水")

    url = f"http://127.0.0.1:{_free_port()}/mcp"
    await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

    response = await client.post(f"/api/sessions/{session_id}/lookups", json={"token_id": token_id})

    assert response.status_code == 200
    assert response.json()["known_status"] == "Kanji Trainer unavailable"


async def test_lookup_on_a_grammar_particle_is_422(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    token_id = _token_id(text_row, "を")

    response = await client.post(f"/api/sessions/{session_id}/lookups", json={"token_id": token_id})

    assert response.status_code == 422


async def test_lookup_unknown_token_is_404(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]

    response = await client.post(
        f"/api/sessions/{session_id}/lookups", json={"token_id": "no-such-token"}
    )
    assert response.status_code == 404


# --- finish-reading / answers -----------------------------------------------


async def test_finish_reading_moves_to_questions(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]

    response = await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 30000, "paused_ms": 2000}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "questions"
    assert body["active_ms"] == 30000
    assert body["paused_ms"] == 2000


async def test_answer_checks_server_side_and_is_once_only(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 10000, "paused_ms": 0}
    )

    correct = await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 0}
    )
    assert correct.status_code == 200
    assert correct.json() == {"correct": True, "correct_index": 0}

    wrong = await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 1}
    )
    assert wrong.status_code == 409

    # Session still holds, since question 1 is not answered yet.
    state = await client.get(f"/api/sessions/{session_id}")
    assert state.json()["status"] == "questions"


async def test_answering_before_finishing_reading_is_409(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]

    response = await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 0}
    )
    assert response.status_code == 409


async def test_answering_the_last_question_finishes_the_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 10000, "paused_ms": 0}
    )

    await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 0}
    )
    final = await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 1, "option_index": 1}
    )
    assert final.json() == {"correct": True, "correct_index": 1}

    state = await client.get(f"/api/sessions/{session_id}")
    body = state.json()
    assert body["status"] == "finished"
    assert body["comprehension_correct"] == 2
    assert body["answers"][0]["correct_index"] == 0
    assert body["answers"][1]["correct_index"] == 1


async def test_a_wrong_answer_lowers_comprehension_correct(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 10000, "paused_ms": 0}
    )

    await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 3}
    )
    await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 1, "option_index": 1}
    )

    state = await client.get(f"/api/sessions/{session_id}")
    assert state.json()["comprehension_correct"] == 1


# --- summary -----------------------------------------------------------------


async def test_summary_only_available_once_finished(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]

    response = await client.get(f"/api/sessions/{session_id}/summary")
    assert response.status_code == 409


async def test_summary_maths(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    created = await client.post("/api/sessions", json={"text_id": text_row.id})
    session_id = created.json()["id"]
    token_id = _token_id(text_row, "水")

    # One minute of active time exactly, so chars/words per minute equal the
    # measured metrics themselves.
    await client.post(
        f"/api/sessions/{session_id}/helps", json={"kind": "reading_peek", "token_id": token_id}
    )
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 60000, "paused_ms": 5000}
    )
    await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 0}
    )
    await client.post(
        f"/api/sessions/{session_id}/answers", json={"question_index": 1, "option_index": 1}
    )

    response = await client.get(f"/api/sessions/{session_id}/summary")
    assert response.status_code == 200
    body = response.json()

    metrics = text_row.analysis["metrics"]
    assert body["chars_per_minute"] == metrics["characters"]
    assert body["words_per_minute"] == metrics["words"]
    assert body["helps_per_100_words"] == round(1 / metrics["words"] * 100, 1)
    assert body["questions_correct"] == 2
    assert body["questions_total"] == 2
    assert body["active_ms"] == 60000


# --- pace --------------------------------------------------------------------


async def test_pace_defaults_with_too_few_sessions(client: AsyncClient) -> None:
    response = await client.get("/api/reading/pace")
    assert response.status_code == 200
    assert response.json() == {"chars_per_minute": 150, "source": "default", "sessions": 0}


async def test_pace_uses_history_once_enough_sessions_finished(
    client: AsyncClient, session: AsyncSession
) -> None:
    texts = [await _create_text(session) for _ in range(3)]
    characters = texts[0].analysis["metrics"]["characters"]

    # Three finished first reads at 1/2/3 minutes -> chars/min of
    # characters*60, characters*30, characters*20 -- median is the middle one.
    import datetime as dt

    for text_row, active_ms in zip(texts, (60_000, 120_000, 180_000), strict=True):
        row = ReadingSession(
            text_id=text_row.id,
            status="finished",
            active_ms=active_ms,
            answers=[0, 0],
            finished_at=dt.datetime.now(dt.timezone.utc),
        )
        session.add(row)
    await session.commit()

    response = await client.get("/api/reading/pace")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "history"
    assert body["sessions"] == 3
    expected_median = round(characters / 2.0)  # the 120_000ms (2 min) session
    assert body["chars_per_minute"] == expected_median


async def test_pace_ignores_rereads_of_the_same_text(
    client: AsyncClient, session: AsyncSession
) -> None:
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    texts = [await _create_text(session) for _ in range(3)]
    characters = texts[0].analysis["metrics"]["characters"]
    # First reads at 2 minutes each, then a fast re-read of the first text.
    for offset, text_row in enumerate(texts):
        session.add(
            ReadingSession(
                text_id=text_row.id,
                status="finished",
                active_ms=120_000,
                answers=[0, 0],
                finished_at=now + dt.timedelta(minutes=offset),
            )
        )
    session.add(
        ReadingSession(
            text_id=texts[0].id,
            status="finished",
            active_ms=10_000,
            answers=[0, 0],
            finished_at=now + dt.timedelta(minutes=10),
        )
    )
    await session.commit()

    body = (await client.get("/api/reading/pace")).json()
    assert body["sessions"] == 3
    assert body["chars_per_minute"] == round(characters / 2.0)
