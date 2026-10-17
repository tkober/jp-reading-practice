"""`generate_text()` against a fake OpenAI server and the fake Kanji Trainer
MCP server from `test_kanji_trainer.py` (issue #8)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import generation
from app.generation import GenerationError
from app.models import JlptMixTarget
from app.runtime_config import RuntimeConfig
from tests.test_kanji_trainer import _State
from tests.test_kanji_trainer import _build_app as _build_kanji_trainer_app
from tests.test_kanji_trainer import _free_port
from tests.test_kanji_trainer import _running as _running_mcp


# --- fake OpenAI chat-completions server --------------------------------------


@dataclass
class _OpenAIState:
    #: One response body per call, in order; the last one repeats if more
    #: calls happen than entries exist.
    responses: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    status_code: int = 200
    error_detail: str = "upstream failure"


def _completion_body(
    *,
    title: str,
    paragraphs: list[str],
    questions: list[dict[str, Any]],
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    cached_tokens: int = 0,
) -> dict[str, Any]:
    content = json.dumps({"title": title, "paragraphs": paragraphs, "questions": questions})
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        },
    }


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
        return JSONResponse(content=state.responses[index])

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


def _config(*, openai_api_base: str, kanji_trainer_url: str, api_key: str = "sk-test") -> RuntimeConfig:
    return RuntimeConfig(
        openai_api_key=api_key,
        generation_model="gpt-4o-mini",
        help_model="gpt-4o",
        kanji_trainer_mcp_url=kanji_trainer_url,
        web_search_enabled=False,
        openai_api_base=openai_api_base,
    )


VALID_QUESTIONS = [
    {"question": "What did the cat do?", "options": ["Slept", "Ran", "Ate", "Sang"], "answer_index": 0},
    {"question": "Where was it?", "options": ["Garden", "Roof", "Kitchen", "Car"], "answer_index": 1},
]


# --- happy path -----------------------------------------------------------------


async def test_happy_path_no_correction_needed() -> None:
    state = _OpenAIState(
        responses=[
            _completion_body(
                title="水曜日",
                paragraphs=["水曜日です。水を飲みます。"],
                questions=VALID_QUESTIONS,
            )
        ]
    )
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        async with _running_mcp(_build_kanji_trainer_app(_build_fresh_state()), _free_port()) as kt_url:
            outcome = await generation.generate_text(
                config=_config(openai_api_base=openai_url, kanji_trainer_url=kt_url),
                kanji_trainer_url=kt_url,
                topic_prompt="Write about the days of the week.",
                style="casual",
                length_chars=10,  # close to this text's own length (~11 characters)
                jlpt_mix=JlptMixTarget(n5=1.0),
                unknown_kanji_target=0.9,  # generous -- this text should not need correction
            )

    assert outcome.attempts == 1
    assert outcome.title == "水曜日"
    assert "水曜日" in outcome.body
    assert len(outcome.questions) == 2
    assert len(state.requests) == 1
    assert outcome.kanji_trainer_error is None
    assert outcome.known_snapshot["known_kanji_count"] >= 1


# --- correction round: triggered, and the closer attempt is kept --------------


async def test_correction_round_triggers_on_unknown_kanji_and_keeps_the_better_attempt() -> None:
    # First attempt: heavy on unknown kanji (only 水 is known by the fake
    # Kanji Trainer). Second attempt: almost entirely 水/kana -- much closer
    # to a low unknown-kanji target.
    first = _completion_body(
        title="難しい話",
        paragraphs=["経済学的観点から見れば非常に複雑な現象である。"],
        questions=VALID_QUESTIONS,
    )
    second = _completion_body(
        title="水の話",
        paragraphs=["水です。水がすきです。水をのみます。"],
        questions=VALID_QUESTIONS,
    )
    state = _OpenAIState(responses=[first, second])

    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        async with _running_mcp(_build_kanji_trainer_app(_build_fresh_state()), _free_port()) as kt_url:
            outcome = await generation.generate_text(
                config=_config(openai_api_base=openai_url, kanji_trainer_url=kt_url),
                kanji_trainer_url=kt_url,
                topic_prompt="Write about economics.",
                style="formal",
                length_chars=20,
                jlpt_mix=JlptMixTarget(n5=1.0),
                unknown_kanji_target=0.05,
            )

    assert outcome.attempts == 2
    assert len(state.requests) == 2
    # The correction turn must name the first attempt's own offending words.
    correction_message = state.requests[1]["messages"][-1]["content"]
    assert "難" in correction_message or "経済" in correction_message
    # The far-better second attempt was kept.
    assert outcome.title == "水の話"


async def test_correction_round_can_keep_the_first_attempt_if_it_was_closer() -> None:
    # First attempt is already good; a (hypothetical) correction is forced
    # by a deliberately tiny target, but the "revision" the fake server
    # returns is worse -- the picker must keep the first attempt anyway.
    # A touch of unknown kanji (猫) so a tiny target still triggers a
    # correction round, while staying far better than `worse` below.
    good = _completion_body(
        title="水の話",
        paragraphs=["水です。水がすきです。猫も水をのみます。"],
        questions=VALID_QUESTIONS,
    )
    worse = _completion_body(
        title="難しい話",
        paragraphs=["経済学的観点から見れば非常に複雑な現象である。"],
        questions=VALID_QUESTIONS,
    )
    state = _OpenAIState(responses=[good, worse])

    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        async with _running_mcp(_build_kanji_trainer_app(_build_fresh_state()), _free_port()) as kt_url:
            outcome = await generation.generate_text(
                config=_config(openai_api_base=openai_url, kanji_trainer_url=kt_url),
                kanji_trainer_url=kt_url,
                topic_prompt="Write about water.",
                style="casual",
                length_chars=20,
                # Target is tiny enough that even the good attempt still
                # triggers (1.5x + margin over ~0), to exercise the
                # keep-the-first-attempt branch deterministically.
                jlpt_mix=JlptMixTarget(n5=1.0),
                unknown_kanji_target=0.001,
            )

    assert outcome.attempts == 2
    assert outcome.title == "水の話"


# --- question validation --------------------------------------------------------


async def test_invalid_questions_are_dropped_but_valid_ones_kept() -> None:
    questions = [
        *VALID_QUESTIONS,
        {"question": "Bad: duplicate options", "options": ["A", "A", "B", "C"], "answer_index": 0},
        {"question": "Bad: index out of range", "options": ["A", "B", "C", "D"], "answer_index": 9},
        {"question": "Bad: only 3 options", "options": ["A", "B", "C"], "answer_index": 0},
    ]
    state = _OpenAIState(
        responses=[
            _completion_body(title="水曜日", paragraphs=["水を飲みます。"], questions=questions)
        ]
    )

    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        async with _running_mcp(_build_kanji_trainer_app(_build_fresh_state()), _free_port()) as kt_url:
            outcome = await generation.generate_text(
                config=_config(openai_api_base=openai_url, kanji_trainer_url=kt_url),
                kanji_trainer_url=kt_url,
                topic_prompt="Water.",
                style="casual",
                length_chars=6,  # matches "水を飲みます。"'s own length
                jlpt_mix=JlptMixTarget(n5=1.0),
                unknown_kanji_target=0.9,
            )

    assert len(outcome.questions) == 2
    assert {q.question for q in outcome.questions} == {q["question"] for q in VALID_QUESTIONS}


async def test_fewer_than_two_valid_questions_is_an_error() -> None:
    state = _OpenAIState(
        responses=[
            _completion_body(
                title="水曜日",
                paragraphs=["水を飲みます。"],
                questions=[VALID_QUESTIONS[0]],  # only one valid question
            )
        ]
    )

    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        async with _running_mcp(_build_kanji_trainer_app(_build_fresh_state()), _free_port()) as kt_url:
            with pytest.raises(GenerationError, match="too few valid"):
                await generation.generate_text(
                    config=_config(openai_api_base=openai_url, kanji_trainer_url=kt_url),
                    kanji_trainer_url=kt_url,
                    topic_prompt="Water.",
                    style="casual",
                    length_chars=6,  # matches "水を飲みます。"'s own length
                    jlpt_mix=JlptMixTarget(n5=1.0),
                    unknown_kanji_target=0.9,
                )


# --- errors -----------------------------------------------------------------------


async def test_no_api_key_is_a_409() -> None:
    with pytest.raises(GenerationError) as excinfo:
        await generation.generate_text(
            config=_config(openai_api_base="http://127.0.0.1:1/v1", kanji_trainer_url="http://127.0.0.1:1/mcp", api_key=""),
            kanji_trainer_url="http://127.0.0.1:1/mcp",
            topic_prompt="Water.",
            style="casual",
            length_chars=10,
            jlpt_mix=JlptMixTarget(n5=1.0),
            unknown_kanji_target=0.9,
        )
    assert excinfo.value.status == 409


async def test_upstream_openai_error_is_a_502() -> None:
    state = _OpenAIState(status_code=500, error_detail="internal error")

    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        async with _running_mcp(_build_kanji_trainer_app(_build_fresh_state()), _free_port()) as kt_url:
            with pytest.raises(GenerationError) as excinfo:
                await generation.generate_text(
                    config=_config(openai_api_base=openai_url, kanji_trainer_url=kt_url),
                    kanji_trainer_url=kt_url,
                    topic_prompt="Water.",
                    style="casual",
                    length_chars=10,
                    jlpt_mix=JlptMixTarget(n5=1.0),
                    unknown_kanji_target=0.9,
                )
    assert excinfo.value.status == 502


async def test_kanji_trainer_down_still_generates_without_the_known_list() -> None:
    state = _OpenAIState(
        responses=[
            _completion_body(title="水曜日", paragraphs=["水を飲みます。"], questions=VALID_QUESTIONS)
        ]
    )
    unreachable_kt_url = f"http://127.0.0.1:{_free_port()}/mcp"

    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        outcome = await generation.generate_text(
            config=_config(openai_api_base=openai_url, kanji_trainer_url=unreachable_kt_url),
            kanji_trainer_url=unreachable_kt_url,
            topic_prompt="Water.",
            style="casual",
            length_chars=6,  # matches "水を飲みます。"'s own length
            jlpt_mix=JlptMixTarget(n5=1.0),
            unknown_kanji_target=1.0,  # avoid a correction round on an all-unknown text
        )

    assert outcome.kanji_trainer_error is not None
    assert "unreachable" in outcome.kanji_trainer_error
    assert outcome.known_snapshot["kanji_trainer_error"] == outcome.kanji_trainer_error
    assert outcome.known_snapshot["known_kanji_count"] == 0
    # The prompt sent to the model must say the known list is unavailable.
    sent_system_prompt = state.requests[0]["messages"][0]["content"]
    assert "unavailable" in sent_system_prompt


def _build_fresh_state() -> _State:
    return _State()
