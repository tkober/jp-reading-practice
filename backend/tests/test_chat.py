"""The tutor chat (issue #11): `app.assist.generate_chat_answer()` against a
fake OpenAI server (same shape as `test_assist.py`), then `GET`/`POST
/api/sessions/{id}/chat`'s own wiring -- question + answer stored, history
sent in order on the second question, the focus prefix, every question
counted (never deduped), the wrong-status 409, empty/too-long 422, no-key
409 keeping the user message, an upstream 502 keeping the user message, and
the summary's `chat_questions`/`assists_cost_usd`.
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
from sqlalchemy.ext.asyncio import AsyncSession

from app import assist
from app.analysis import analyze
from app.db import ChatMessage, GeneratedText
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
# Same shape as `test_assist.py`'s own fixture.


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


# --- app.assist.generate_chat_answer() --------------------------------------


async def test_generate_chat_answer_sends_the_given_messages_verbatim() -> None:
    state = _OpenAIState(responses=["猫は水を飲んでいます。"])
    messages = [
        {"role": "system", "content": "You are a tutor."},
        {"role": "user", "content": "猫は何をしていますか？"},
    ]
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        answer, usage = await assist.generate_chat_answer(
            config=_config(openai_api_base=openai_url), messages=messages
        )
    assert answer == "猫は水を飲んでいます。"
    assert usage.prompt_tokens == 50
    assert state.requests[0]["messages"] == messages


async def test_generate_chat_answer_no_key_is_409() -> None:
    with pytest.raises(GenerationError) as excinfo:
        await assist.generate_chat_answer(
            config=_config(openai_api_base="http://127.0.0.1:1/v1", api_key=""), messages=[]
        )
    assert excinfo.value.status == 409


async def test_generate_chat_answer_upstream_error_is_502() -> None:
    state = _OpenAIState(status_code=500, error_detail="internal error")
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        with pytest.raises(GenerationError) as excinfo:
            await assist.generate_chat_answer(
                config=_config(openai_api_base=openai_url), messages=[{"role": "user", "content": "x"}]
            )
    assert excinfo.value.status == 502


# --- GET/POST /api/sessions/{id}/chat ---------------------------------------


def _patch_answer(monkeypatch: pytest.MonkeyPatch, *, text: str, calls: list[list[dict]] | None = None):
    from app.api import sessions as sessions_api
    from app.pricing import CallUsage

    async def fake_generate_chat_answer(*, config, messages: list[dict[str, str]]):
        if calls is not None:
            calls.append(messages)
        return text, CallUsage(prompt_tokens=100, completion_tokens=40, cached_tokens=0)

    monkeypatch.setattr(sessions_api, "generate_chat_answer", fake_generate_chat_answer)


async def test_question_and_answer_are_stored(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    _patch_answer(monkeypatch, text="猫は水を飲んでいます。")

    response = await client.post(
        f"/api/sessions/{session_id}/chat", json={"content": "猫は何をしていますか？"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == "猫は何をしていますか？"
    assert body["user_message"]["focus_sentence_key"] is None
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["content"] == "猫は水を飲んでいます。"
    assert body["counted"] is True
    assert body["weight"] == 3

    rows = list(
        await session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        )
    )
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[1].model == "gpt-4o"
    assert rows[1].cost_usd is not None and rows[1].cost_usd > 0


async def test_history_is_sent_in_order_on_the_second_question(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    calls: list[list[dict]] = []

    _patch_answer(monkeypatch, text="猫は水を飲んでいます。", calls=calls)
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "猫は何をしていますか？"})

    _patch_answer(monkeypatch, text="喉が渇いていたからです。", calls=calls)
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "なぜですか？"})

    assert len(calls) == 2
    # The first call had no history yet: system + the one new question.
    assert [m["role"] for m in calls[0]] == ["system", "user"]

    # The second call carries the first Q&A as history, oldest first, ahead
    # of the new question.
    second_messages = calls[1]
    assert [m["role"] for m in second_messages] == ["system", "user", "assistant", "user"]
    assert second_messages[1] == {"role": "user", "content": "猫は何をしていますか？"}
    assert second_messages[2] == {"role": "assistant", "content": "猫は水を飲んでいます。"}
    assert second_messages[3] == {"role": "user", "content": "なぜですか？"}


async def test_focus_token_prefixes_the_question_and_is_stored_on_the_user_message(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")  # in the first sentence, "水を飲みます。"
    calls: list[list[dict]] = []
    _patch_answer(monkeypatch, text="「水」は water という意味です。", calls=calls)

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"content": "これは何の意味ですか？", "focus_token_id": token_id},
    )
    assert response.status_code == 200
    assert response.json()["user_message"]["focus_sentence_key"] == "0-0"

    final_question = calls[0][-1]
    assert final_question["role"] == "user"
    assert final_question["content"] == "About this sentence: 水を飲みます。\n\nこれは何の意味ですか？"

    # The stored message itself keeps the raw content, without the prefix --
    # only the prompt sent to the model gets it.
    rows = list(await session.scalars(select(ChatMessage).where(ChatMessage.role == "user")))
    assert rows[0].content == "これは何の意味ですか？"


async def test_unknown_focus_token_is_404(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"content": "これは何の意味ですか？", "focus_token_id": "no-such-token"},
    )
    assert response.status_code == 404


async def test_every_question_is_counted_even_with_the_same_focus_and_text(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unlike /assist's per-target dedupe, the chat is never cached and every
    # question counts -- `target` is "chat:<user message id>", always
    # unique, even for the exact same focus token asked twice.
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")
    _patch_answer(monkeypatch, text="answer")

    first = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"content": "これは何ですか？", "focus_token_id": token_id},
    )
    second = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"content": "これは何ですか？", "focus_token_id": token_id},
    )

    assert first.json()["counted"] is True
    assert second.json()["counted"] is True


async def test_chat_outside_reading_is_409(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 1000, "paused_ms": 0}
    )

    response = await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問です。"})
    assert response.status_code == 409


async def test_empty_content_is_422(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    response = await client.post(f"/api/sessions/{session_id}/chat", json={"content": "   "})
    assert response.status_code == 422


async def test_too_long_content_is_422(client: AsyncClient, session: AsyncSession) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    response = await client.post(
        f"/api/sessions/{session_id}/chat", json={"content": "あ" * 1001}
    )
    assert response.status_code == 422


async def test_no_openai_key_is_409_and_keeps_the_user_message(
    client: AsyncClient, session: AsyncSession
) -> None:
    # conftest.py's test environment starts with an empty OPENAI_API_KEY and
    # no settings-row override -- no monkeypatching needed to hit this path.
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    response = await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問です。"})
    assert response.status_code == 409
    assert "No OpenAI API key" in response.json()["detail"]

    history = await client.get(f"/api/sessions/{session_id}/chat")
    assert history.status_code == 200
    assert [row["role"] for row in history.json()] == ["user"]
    assert history.json()[0]["content"] == "質問です。"


async def test_upstream_error_is_502_and_keeps_the_user_message(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import sessions as sessions_api

    async def failing(*, config, messages):
        raise GenerationError("The OpenAI API returned HTTP 500: boom", status=502)

    monkeypatch.setattr(sessions_api, "generate_chat_answer", failing)

    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    response = await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問です。"})
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]

    history = await client.get(f"/api/sessions/{session_id}/chat")
    assert [row["role"] for row in history.json()] == ["user"]


async def test_get_chat_returns_history_in_order(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    _patch_answer(monkeypatch, text="答えです。")
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問1"})
    _patch_answer(monkeypatch, text="もう一つの答え")
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問2"})

    response = await client.get(f"/api/sessions/{session_id}/chat")
    assert response.status_code == 200
    contents = [row["content"] for row in response.json()]
    assert contents == ["質問1", "答えです。", "質問2", "もう一つの答え"]


# --- summary (chat_questions / assists_cost_usd) ----------------------------


async def test_summary_counts_chat_questions_and_their_cost(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    _patch_answer(monkeypatch, text="答え1")
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問1"})
    _patch_answer(monkeypatch, text="答え2")
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問2"})

    await client.post(
        f"/api/sessions/{session_id}/finish-reading", json={"active_ms": 60000, "paused_ms": 0}
    )
    await client.post(f"/api/sessions/{session_id}/answers", json={"question_index": 0, "option_index": 0})
    await client.post(f"/api/sessions/{session_id}/answers", json={"question_index": 1, "option_index": 1})

    response = await client.get(f"/api/sessions/{session_id}/summary")
    assert response.status_code == 200
    body = response.json()

    metrics = text_row.analysis["metrics"]
    assert body["chat_questions"] == 2
    # Two tutor helps at weight 3 each -- helps_per_100_words already sums
    # every kind's weight, tutor included.
    assert body["helps_per_100_words"] == round(6 / metrics["words"] * 100, 1)
    assert body["assists_cost_usd"] > 0


async def test_a_failed_question_is_left_out_of_the_history_sent_to_the_model(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import sessions as sessions_api

    async def failing(*, config, messages):
        raise GenerationError("The OpenAI API returned HTTP 500: boom", status=502)

    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)

    monkeypatch.setattr(sessions_api, "generate_chat_answer", failing)
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問です。"})

    calls: list[list[dict]] = []
    _patch_answer(monkeypatch, text="答えです。", calls=calls)
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "質問です。"})

    # The resend is the only question the model sees -- not the failed one too.
    assert [m["role"] for m in calls[0]] == ["system", "user"]


async def test_focus_end_token_id_prefixes_the_question_with_the_span(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    start_id = _token_id(text_row, "水")
    end_id = _token_id(text_row, "飲み")  # を rides along; "水を飲み" is the span
    calls: list[list[dict]] = []
    _patch_answer(monkeypatch, text="「水」は water という意味です。", calls=calls)

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "content": "これは何の意味ですか？",
            "focus_token_id": start_id,
            "focus_end_token_id": end_id,
        },
    )
    assert response.status_code == 200

    final_question = calls[0][-1]
    assert final_question["content"] == (
        "About this part of a sentence: 水を飲み (in: 水を飲みます。)\n\nこれは何の意味ですか？"
    )

    # The stored message keeps the raw content -- only the prompt gets the
    # prefix -- but `focus_sentence_key` is now the span target, not a
    # plain sentence key (issue #32: reused, unparsed, no schema change).
    rows = list(await session.scalars(select(ChatMessage).where(ChatMessage.role == "user")))
    assert rows[0].content == "これは何の意味ですか？"
    assert rows[0].focus_sentence_key == f"0-0:{start_id}-{end_id}"


async def test_focus_end_token_id_counts_the_same_weight(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    start_id = _token_id(text_row, "水")
    end_id = _token_id(text_row, "飲み")
    _patch_answer(monkeypatch, text="answer")

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "content": "これは何ですか？",
            "focus_token_id": start_id,
            "focus_end_token_id": end_id,
        },
    )
    assert response.json()["weight"] == 3


async def test_focus_end_token_id_single_word_span_is_422(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    start_id = _token_id(text_row, "水")

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "content": "これは何ですか？",
            "focus_token_id": start_id,
            "focus_end_token_id": start_id,
        },
    )
    assert response.status_code == 422


async def test_focus_end_token_id_across_sentences_is_422(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    start_id = _token_id(text_row, "水")  # "水を飲みます。"
    end_id = _token_id(text_row, "猫")  # "猫がいます。" -- a different sentence

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "content": "これは何ですか？",
            "focus_token_id": start_id,
            "focus_end_token_id": end_id,
        },
    )
    assert response.status_code == 422


async def test_focus_end_token_id_unknown_is_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    start_id = _token_id(text_row, "水")

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "content": "これは何ですか？",
            "focus_token_id": start_id,
            "focus_end_token_id": "no-such-token",
        },
    )
    assert response.status_code == 404


async def test_focus_end_token_id_without_focus_token_id_is_ignored(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `focus_end_token_id` is never even looked at without `focus_token_id`
    # (model docstring) -- not a validation error, simply no focus at all.
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    end_id = _token_id(text_row, "飲み")
    _patch_answer(monkeypatch, text="answer")

    response = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"content": "これは何ですか？", "focus_end_token_id": end_id},
    )
    assert response.status_code == 200
    assert response.json()["user_message"]["focus_sentence_key"] is None


async def test_an_earlier_span_focused_question_keeps_its_span_focus_in_the_history(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    start_id = _token_id(text_row, "水")
    end_id = _token_id(text_row, "飲み")
    calls: list[list[dict]] = []

    _patch_answer(monkeypatch, text="water", calls=calls)
    await client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "content": "これは何の意味ですか？",
            "focus_token_id": start_id,
            "focus_end_token_id": end_id,
        },
    )
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "もう一度？"})

    assert calls[1][1] == {
        "role": "user",
        "content": (
            "About this part of a sentence: 水を飲み (in: 水を飲みます。)\n\nこれは何の意味ですか？"
        ),
    }


async def test_an_earlier_focused_question_keeps_its_focus_in_the_history(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_row = await _create_text(session)
    session_id = await _new_session_id(client, text_row.id)
    token_id = _token_id(text_row, "水")
    calls: list[list[dict]] = []

    _patch_answer(monkeypatch, text="water", calls=calls)
    await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"content": "これは何の意味ですか？", "focus_token_id": token_id},
    )
    await client.post(f"/api/sessions/{session_id}/chat", json={"content": "もう一度？"})

    assert calls[1][1] == {
        "role": "user",
        "content": "About this sentence: 水を飲みます。\n\nこれは何の意味ですか？",
    }
