"""The LLM helps (issue #10): `app.assist.generate_help_answer()` against a
fake OpenAI server (same shape as `test_generation.py`), then
`POST /api/sessions/{id}/assist`'s own wiring -- each kind, caching across
two sessions, per-session dedupe, the particle 422, the wrong-status 409,
no-key 409, an upstream error mapped to 502, and the schema migration's
backfill.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app import assist
from app.analysis import analyze
from app.db import GeneratedText, HelpAnswer
from app.generation import GenerationError
from app.known_set import KnownSet
from app.runtime_config import RuntimeConfig
from tests.test_kanji_trainer import _free_port

BODY = "水を飲みます。猫がいます。"
QUESTIONS = [
    {"question": "What did they drink?", "options": ["Water", "Tea", "Milk", "Juice"], "answer_index": 0},
    {"question": "What animal is there?", "options": ["Dog", "Cat", "Bird", "Fish"], "answer_index": 1},
]


async def _create_text(session: AsyncSession, *, body: str = BODY) -> GeneratedText:
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
        questions=list(QUESTIONS),
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


async def _new_session_id(client: AsyncClient, text_id: int) -> int:
    created = await client.post("/api/sessions", json={"text_id": text_id})
    assert created.status_code == 201
    return created.json()["id"]


# --- fake OpenAI chat-completions server (plain text, no schema) -----------


@dataclass
class _OpenAIState:
    responses: list[str] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    status_code: int = 200
    error_detail: str = "upstream failure"


def _build_openai_app(state: _OpenAIState) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        payload = await request.json()
        state.requests.append(payload)
        if state.status_code != 200:
            return JSONResponse(
                status_code=state.status_code, content={"error": {"message": state.error_detail}}
            )
        index = min(len(state.requests) - 1, len(state.responses) - 1)
        return JSONResponse(
            content={
                "choices": [{"message": {"content": state.responses[index]}}],
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            }
        )

    return app


@contextlib.asynccontextmanager
async def _running_http(app: FastAPI, port: int) -> AsyncIterator[str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("fake OpenAI server did not start in time")
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _config(*, openai_api_base: str, api_key: str = "sk-test") -> RuntimeConfig:
    return RuntimeConfig(
        openai_api_key=api_key,
        generation_model="gpt-4o-mini",
        help_model="gpt-4o",
        kanji_trainer_mcp_url="http://127.0.0.1:1/mcp",
        web_search_enabled=False,
        openai_api_base=openai_api_base,
    )


# --- app.assist.generate_help_answer() --------------------------------------


async def test_generate_help_answer_happy_path() -> None:
    state = _OpenAIState(responses=["飲む means to drink."])
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        answer, usage = await assist.generate_help_answer(
            config=_config(openai_api_base=openai_url), prompt="Explain 飲む."
        )
    assert answer == "飲む means to drink."
    assert usage.prompt_tokens == 50
    assert usage.completion_tokens == 20


async def test_generate_help_answer_no_key_is_409() -> None:
    with pytest.raises(GenerationError) as excinfo:
        await assist.generate_help_answer(
            config=_config(openai_api_base="http://127.0.0.1:1/v1", api_key=""), prompt="x"
        )
    assert excinfo.value.status == 409


async def test_generate_help_answer_upstream_error_is_502() -> None:
    state = _OpenAIState(status_code=500, error_detail="internal error")
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        with pytest.raises(GenerationError) as excinfo:
            await assist.generate_help_answer(config=_config(openai_api_base=openai_url), prompt="x")
    assert excinfo.value.status == 502


async def test_generate_help_answer_refusal_is_an_error() -> None:
    state = _OpenAIState(responses=[])

    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        return JSONResponse(content={"choices": [{"message": {"refusal": "cannot help with that"}}]})

    async with _running_http(app, _free_port()) as openai_url:
        with pytest.raises(GenerationError, match="refused"):
            await assist.generate_help_answer(config=_config(openai_api_base=openai_url), prompt="x")


# --- POST /api/sessions/{id}/assist -----------------------------------------


def _patch_answer(monkeypatch: pytest.MonkeyPatch, *, text: str, calls: list[str] | None = None):
    from app.api import sessions as sessions_api
    from app.pricing import CallUsage

    async def fake_generate_help_answer(*, config, prompt: str):
        if calls is not None:
            calls.append(prompt)
        return text, CallUsage(prompt_tokens=100, completion_tokens=40, cached_tokens=0)

    monkeypatch.setattr(sessions_api, "generate_help_answer", fake_generate_help_answer)


async def test_explain_word_generates_and_caches(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")
    calls: list[str] = []
    _patch_answer(monkeypatch, text="水 means water.", calls=calls)

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "kind": "explain",
        "answer": "水 means water.",
        "cached": False,
        "counted": True,
        "weight": 2,
    }
    assert len(calls) == 1

    # The sentence/word was actually given to the prompt builder.
    assert "水" in calls[0]

    cached_row = await session.scalar(
        select(HelpAnswer).where(HelpAnswer.text_id == text_row.id)
    )
    assert cached_row is not None
    assert cached_row.kind == "explain"
    assert cached_row.target == "0-0:水"  # sentence key + lemma, for explain
    assert cached_row.answer == "水 means water."
    assert cached_row.cost_usd is not None and cached_row.cost_usd > 0


async def test_translate_and_grammar_use_the_sentence_key_as_target(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")  # in the first sentence, "水を飲みます。"

    for kind, answer in (("translate", "I drink water."), ("grammar", "を marks the object.")):
        _patch_answer(monkeypatch, text=answer)
        response = await client.post(
            f"/api/sessions/{session_id}/assist", json={"kind": kind, "token_id": token_id}
        )
        assert response.status_code == 200
        assert response.json()["answer"] == answer

    rows = list(await session.scalars(select(HelpAnswer)))
    targets = {(row.kind, row.target) for row in rows}
    assert targets == {("translate", "0-0"), ("grammar", "0-0")}


async def test_cache_hit_across_two_sessions_skips_the_llm_call(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    token_id = _token_id(text_row, "水")
    calls: list[str] = []
    _patch_answer(monkeypatch, text="水 means water.", calls=calls)

    first_session_id = await _new_session_id(client, text_row.id)
    first = await client.post(
        f"/api/sessions/{first_session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert first.json()["cached"] is False
    assert len(calls) == 1

    second_session_id = await _new_session_id(client, text_row.id)
    second = await client.post(
        f"/api/sessions/{second_session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert second.json()["cached"] is True
    assert second.json()["answer"] == "水 means water."
    assert second.json()["counted"] is True  # first ask of this target in *this* session
    assert len(calls) == 1  # no second LLM call


async def test_repeated_ask_in_the_same_session_is_not_counted(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")
    _patch_answer(monkeypatch, text="水 means water.")

    first = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert first.json()["counted"] is True

    second = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert second.json()["counted"] is False
    assert second.json()["cached"] is True  # already in help_answers from the first ask


async def test_explain_on_a_particle_is_422(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "を")

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert response.status_code == 422


async def test_translate_on_a_particle_is_allowed(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only `explain` is word-only (brief) -- translate/grammar act on the
    # sentence, so tapping a particle must still work for those two.
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "を")
    _patch_answer(monkeypatch, text="I drink water.")

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "translate", "token_id": token_id}
    )
    assert response.status_code == 200


async def test_assist_outside_reading_is_409(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 1000, "paused_ms": 0}
    )

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert response.status_code == 409


async def test_assist_with_no_openai_key_is_409(client: AsyncClient, session: AsyncSession) -> None:
    # conftest.py's test environment starts with an empty OPENAI_API_KEY and
    # no settings-row override -- no monkeypatching needed to hit this path.
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert response.status_code == 409
    assert "No OpenAI API key" in response.json()["detail"]


async def test_upstream_openai_error_is_mapped_to_502(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import sessions as sessions_api

    async def failing(*, config, prompt: str):
        raise GenerationError("The OpenAI API returned HTTP 500: boom", status=502)

    monkeypatch.setattr(sessions_api, "generate_help_answer", failing)

    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": token_id}
    )
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


async def test_assist_unknown_token_is_404(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    response = await client.post(
        f"/api/sessions/{session_id}/assist", json={"kind": "explain", "token_id": "no-such-token"}
    )
    assert response.status_code == 404


# --- migration 0004's backfill ----------------------------------------------


async def test_migration_0004_backfills_target_from_lemma(session: AsyncSession) -> None:
    """Downgrade to the pre-#10 schema, insert a row the old way (no
    `target` column), upgrade back to head, and check `target` ends up
    equal to `lemma` for that pre-existing row."""
    from alembic import command as alembic_command

    from app.config import get_settings
    from app.db import _alembic_config, _new_engine

    def _migrate(sync_conn, revision: str) -> None:
        config = _alembic_config()
        config.attributes["connection"] = sync_conn
        if revision == "head":
            alembic_command.upgrade(config, revision)
        else:
            alembic_command.downgrade(config, revision)

    owner_engine = _new_engine(get_settings().owner_database_url)
    try:
        async with owner_engine.begin() as conn:
            await conn.run_sync(_migrate, "0003")
    finally:
        await owner_engine.dispose()

    text_row = await _create_text(session)
    session_row = await session.execute(
        sa_text("INSERT INTO reading_sessions (text_id) VALUES (:tid) RETURNING id"),
        {"tid": text_row.id},
    )
    session_id = session_row.scalar_one()
    await session.execute(
        sa_text(
            "INSERT INTO help_events (session_id, kind, token_id, lemma, surface, weight, at_ms) "
            "VALUES (:sid, 'reading_peek', '0-0', :lemma, :surface, 1, 0)"
        ),
        {"sid": session_id, "lemma": "水", "surface": "水"},
    )
    await session.commit()

    owner_engine = _new_engine(get_settings().owner_database_url)
    try:
        async with owner_engine.begin() as conn:
            await conn.run_sync(_migrate, "head")
    finally:
        await owner_engine.dispose()

    result = await session.execute(
        sa_text("SELECT target, lemma FROM help_events WHERE session_id = :sid"), {"sid": session_id}
    )
    row = result.one()
    assert row.target == row.lemma == "水"
