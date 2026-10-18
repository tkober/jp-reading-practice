"""The AI suggestion for the next text (issue #14): clamping/normalising the
model's raw overrides, `app.suggestions.generate_suggestion()` against a fake
OpenAI server (same shape as `test_generation.py`), and `POST
/api/suggestions`'s own HTTP wiring (stored row + cost, no-key 409, upstream
502, an unknown topic rejected) plus `POST /api/texts`' `suggestion_id`
bookkeeping.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
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

from app import suggestions
from app.db import Suggestion
from app.generation import GeneratedQuestion, GenerationError, GenerationOutcome
from app.analysis import analyze
from app.known_set import KnownSet
from app.models import JlptMixTarget, SuggestionOverridesOut
from app.pricing import CallUsage
from app.runtime_config import RuntimeConfig
from app.suggestion_prompts import SuggestionContext, TopicInfo, time_of_day_label
from tests.test_kanji_trainer import _free_port

# --- pure clamping / normalising --------------------------------------------


def test_clamp_unknown_kanji_target_percent_within_range() -> None:
    assert suggestions.clamp_unknown_kanji_target_percent(8.0) == 8


def test_clamp_unknown_kanji_target_percent_clamps_above() -> None:
    assert suggestions.clamp_unknown_kanji_target_percent(37.0) == 20


def test_clamp_unknown_kanji_target_percent_clamps_below() -> None:
    assert suggestions.clamp_unknown_kanji_target_percent(-5.0) == 0


def test_normalize_jlpt_mix_percent_sums_to_100_in_5_percent_steps() -> None:
    result = suggestions.normalize_jlpt_mix_percent(
        {"n5": 42.0, "n4": 33.0, "n3": 25.0, "n2": 0.0, "n1": 0.0}
    )
    assert result is not None
    total = sum(result.values())
    assert total == pytest.approx(1.0)
    for share in result.values():
        # Every share is a multiple of 5 percentage points (0.05 as a fraction).
        assert round(share * 100 / 5) * 5 == pytest.approx(share * 100)


def test_normalize_jlpt_mix_percent_already_a_multiple_of_5_is_unchanged() -> None:
    result = suggestions.normalize_jlpt_mix_percent(
        {"n5": 50.0, "n4": 35.0, "n3": 15.0, "n2": 0.0, "n1": 0.0}
    )
    assert result == {"n5": 0.50, "n4": 0.35, "n3": 0.15, "n2": 0.0, "n1": 0.0}


def test_normalize_jlpt_mix_percent_scales_a_mix_that_does_not_sum_to_100() -> None:
    # 50 + 30 = 80, not 100 -- scaled up proportionally, then rounded to 5s.
    result = suggestions.normalize_jlpt_mix_percent({"n5": 50.0, "n4": 30.0})
    assert result is not None
    assert sum(result.values()) == pytest.approx(1.0)


def test_normalize_jlpt_mix_percent_drops_an_all_zero_mix() -> None:
    assert suggestions.normalize_jlpt_mix_percent({"n5": 0.0, "n4": 0.0}) is None


def test_normalize_jlpt_mix_percent_drops_a_negative_share() -> None:
    assert suggestions.normalize_jlpt_mix_percent({"n5": -10.0, "n4": 50.0}) is None


def test_resolve_overrides_none_when_nothing_given() -> None:
    assert suggestions.resolve_overrides(None) == None  # noqa: E711 - explicit for clarity


def test_resolve_overrides_drops_an_all_zero_jlpt_mix_but_keeps_style() -> None:
    parsed = suggestions.SuggestedOverrides(
        style="formal", jlpt_mix_percent=suggestions.SuggestedJlptMixPercent()
    )
    resolved = suggestions.resolve_overrides(parsed)
    assert resolved is not None
    assert resolved.style == "formal"
    assert resolved.jlpt_mix is None
    assert resolved.unknown_kanji_target is None


def test_resolve_overrides_clamps_unknown_kanji_target() -> None:
    parsed = suggestions.SuggestedOverrides(unknown_kanji_target_percent=50.0)
    resolved = suggestions.resolve_overrides(parsed)
    assert resolved is not None
    assert resolved.unknown_kanji_target == pytest.approx(0.20)


def test_validate_topic_slug_accepts_a_known_slug() -> None:
    suggestions.validate_topic_slug("daily-life", {"daily-life", "travel"})


def test_validate_topic_slug_rejects_an_unknown_slug() -> None:
    with pytest.raises(GenerationError) as excinfo:
        suggestions.validate_topic_slug("no-such-topic", {"daily-life"})
    assert excinfo.value.status == 502


def test_validate_topic_slug_rejects_surprise() -> None:
    with pytest.raises(GenerationError, match="unknown topic"):
        suggestions.validate_topic_slug("surprise", {"daily-life", "travel"})


# --- fake OpenAI chat-completions server (structured JSON) ------------------


@dataclass
class _OpenAIState:
    responses: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    status_code: int = 200
    error_detail: str = "upstream failure"


def _suggestion_body(
    *,
    topic_slug: str = "daily-life",
    length: str = "short",
    preset: str = "easy",
    overrides: dict[str, Any] | None = None,
    reason: str = "Your last sessions were comfortable, so a gentle pick keeps the streak going.",
    prompt_tokens: int = 300,
    completion_tokens: int = 60,
) -> dict[str, Any]:
    content = json.dumps(
        {
            "topic_slug": topic_slug,
            "length": length,
            "preset": preset,
            "overrides": overrides,
            "reason": reason,
        }
    )
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
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


def _config(*, openai_api_base: str, api_key: str = "sk-test") -> RuntimeConfig:
    return RuntimeConfig(
        openai_api_key=api_key,
        generation_model="gpt-4o-mini",
        help_model="gpt-4o",
        kanji_trainer_mcp_url="http://127.0.0.1:1/mcp",
        web_search_enabled=False,
        openai_api_base=openai_api_base,
    )


_CONTEXT = SuggestionContext(
    topics=[
        TopicInfo(slug="daily-life", title="Daily life", style="casual", news_backed=False),
        TopicInfo(slug="travel", title="Travel", style="polite", news_backed=False),
    ]
)


# --- app.suggestions.generate_suggestion() ----------------------------------


async def test_generate_suggestion_happy_path() -> None:
    state = _OpenAIState(responses=[_suggestion_body()])
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        result = await suggestions.generate_suggestion(
            config=_config(openai_api_base=openai_url),
            context=_CONTEXT,
            valid_topic_slugs={"daily-life", "travel"},
        )
    assert result.topic_slug == "daily-life"
    assert result.length == "short"
    assert result.preset == "easy"
    assert result.overrides is None
    assert "comfortable" in result.reason
    assert result.usage.prompt_tokens == 300
    assert result.model == "gpt-4o"


async def test_generate_suggestion_with_overrides_clamps_them() -> None:
    state = _OpenAIState(
        responses=[
            _suggestion_body(
                overrides={
                    "style": "formal",
                    "unknown_kanji_target_percent": 99.0,
                    "jlpt_mix_percent": {"n5": 50, "n4": 50, "n3": 0, "n2": 0, "n1": 0},
                }
            )
        ]
    )
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        result = await suggestions.generate_suggestion(
            config=_config(openai_api_base=openai_url),
            context=_CONTEXT,
            valid_topic_slugs={"daily-life", "travel"},
        )
    assert result.overrides is not None
    assert result.overrides.style == "formal"
    assert result.overrides.unknown_kanji_target == pytest.approx(0.20)  # clamped from 99%
    assert result.overrides.jlpt_mix == JlptMixTarget(n5=0.50, n4=0.50)


async def test_generate_suggestion_rejects_surprise() -> None:
    state = _OpenAIState(responses=[_suggestion_body(topic_slug="surprise")])
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        with pytest.raises(GenerationError, match="unknown topic") as excinfo:
            await suggestions.generate_suggestion(
                config=_config(openai_api_base=openai_url),
                context=_CONTEXT,
                valid_topic_slugs={"daily-life", "travel"},
            )
    assert excinfo.value.status == 502


async def test_generate_suggestion_rejects_an_unknown_topic() -> None:
    state = _OpenAIState(responses=[_suggestion_body(topic_slug="no-such-topic")])
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        with pytest.raises(GenerationError, match="unknown topic"):
            await suggestions.generate_suggestion(
                config=_config(openai_api_base=openai_url),
                context=_CONTEXT,
                valid_topic_slugs={"daily-life", "travel"},
            )


async def test_generate_suggestion_no_key_is_409() -> None:
    with pytest.raises(GenerationError) as excinfo:
        await suggestions.generate_suggestion(
            config=_config(openai_api_base="http://127.0.0.1:1/v1", api_key=""),
            context=_CONTEXT,
            valid_topic_slugs={"daily-life"},
        )
    assert excinfo.value.status == 409


async def test_generate_suggestion_upstream_error_is_502() -> None:
    state = _OpenAIState(status_code=500, error_detail="internal error")
    async with _running_http(_build_openai_app(state), _free_port()) as openai_url:
        with pytest.raises(GenerationError) as excinfo:
            await suggestions.generate_suggestion(
                config=_config(openai_api_base=openai_url),
                context=_CONTEXT,
                valid_topic_slugs={"daily-life"},
            )
    assert excinfo.value.status == 502


# --- POST /api/suggestions ---------------------------------------------------


def _patch_generate_suggestion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    topic_slug: str = "daily-life",
    length: str = "short",
    preset: str = "easy",
    overrides: SuggestionOverridesOut | None = None,
    reason: str = "Your recent Daily life texts needed few helps.",
    model: str = "gpt-4o-mini",
) -> None:
    from app.api import suggestions as suggestions_api

    async def fake_generate_suggestion(*, config, context, valid_topic_slugs):
        return suggestions.SuggestionResult(
            topic_slug=topic_slug,
            length=length,  # type: ignore[arg-type]
            preset=preset,  # type: ignore[arg-type]
            overrides=overrides,
            reason=reason,
            usage=CallUsage(prompt_tokens=300, completion_tokens=60, cached_tokens=0),
            model=model,
        )

    monkeypatch.setattr(suggestions_api, "generate_suggestion", fake_generate_suggestion)


async def test_create_suggestion_stores_row_and_returns_payload(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    overrides = SuggestionOverridesOut(style="formal", unknown_kanji_target=0.08)
    _patch_generate_suggestion(monkeypatch, overrides=overrides)

    response = await client.post("/api/suggestions")
    assert response.status_code == 201
    body = response.json()
    assert body["topic_slug"] == "daily-life"
    assert body["length"] == "short"
    assert body["preset"] == "easy"
    assert body["overrides"] == {"style": "formal", "unknown_kanji_target": 0.08, "jlpt_mix": None}
    assert "few helps" in body["reason"]

    row = await session.get(Suggestion, body["id"])
    assert row is not None
    assert row.payload["topic_slug"] == "daily-life"
    assert row.payload["overrides"]["style"] == "formal"
    assert row.reason == body["reason"]
    assert row.model == "gpt-4o-mini"
    # gpt-4o-mini has a known rate (pricing.py): 300 prompt + 60 completion tokens.
    assert row.cost_usd == pytest.approx((300 * 0.15 + 60 * 0.60) / 1_000_000)
    assert row.used_text_id is None


async def test_create_suggestion_no_key_is_409(client: AsyncClient) -> None:
    # The test environment starts with no OPENAI_API_KEY and no settings-row
    # override -- reaches the real `generate_suggestion()`, no monkeypatch.
    response = await client.post("/api/suggestions")
    assert response.status_code == 409
    assert "OpenAI API key" in response.json()["detail"]


async def test_create_suggestion_upstream_error_is_502(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import suggestions as suggestions_api

    async def failing(*, config, context, valid_topic_slugs):
        raise GenerationError("The OpenAI API returned HTTP 500: boom", status=502)

    monkeypatch.setattr(suggestions_api, "generate_suggestion", failing)

    response = await client.post("/api/suggestions")
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


async def test_create_suggestion_unknown_topic_is_502(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import suggestions as suggestions_api

    async def failing(*, config, context, valid_topic_slugs):
        raise GenerationError("The suggestion named an unknown topic.")

    monkeypatch.setattr(suggestions_api, "generate_suggestion", failing)

    response = await client.post("/api/suggestions")
    assert response.status_code == 502
    assert "unknown topic" in response.json()["detail"]


# --- POST /api/texts' suggestion_id bookkeeping ------------------------------


def _fake_outcome(**overrides: object) -> GenerationOutcome:
    body = "水を飲みます。猫がいます。"
    text_analysis = analyze(body, KnownSet(), {})
    defaults: dict[str, object] = dict(
        title="水曜日",
        body=body,
        questions=[
            GeneratedQuestion(
                question="What did they drink?", options=["Water", "Tea", "Milk", "Juice"], answer_index=0
            ),
            GeneratedQuestion(
                question="What animal is there?", options=["Dog", "Cat", "Bird", "Fish"], answer_index=1
            ),
        ],
        text_analysis=text_analysis,
        attempts=1,
        calls=[CallUsage(prompt_tokens=100, completion_tokens=50, cached_tokens=0)],
        model="gpt-4o-mini",
        kanji_trainer_error=None,
        known_snapshot={
            "level": None,
            "known_kanji_count": 0,
            "known_vocabulary_count": 0,
            "kanji_trainer_error": None,
        },
    )
    defaults.update(overrides)
    return GenerationOutcome(**defaults)  # type: ignore[arg-type]


async def _patched_generate_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import texts as texts_api

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)


async def test_suggestion_id_marks_used_text_id_when_unchanged(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_generate_suggestion(
        monkeypatch, topic_slug="daily-life", length="short", preset="easy", overrides=None
    )
    suggestion_response = await client.post("/api/suggestions")
    suggestion_id = suggestion_response.json()["id"]

    await _patched_generate_text(monkeypatch)
    text_response = await client.post(
        "/api/texts",
        json={
            "topic_slug": "daily-life",
            "length": "short",
            "preset": "easy",
            "suggestion_id": suggestion_id,
        },
    )
    assert text_response.status_code == 201
    text_id = text_response.json()["id"]

    row = await session.get(Suggestion, suggestion_id)
    await session.refresh(row)
    assert row.used_text_id == text_id


async def test_suggestion_id_not_marked_when_the_learner_changed_something(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_generate_suggestion(
        monkeypatch, topic_slug="daily-life", length="short", preset="easy", overrides=None
    )
    suggestion_response = await client.post("/api/suggestions")
    suggestion_id = suggestion_response.json()["id"]

    await _patched_generate_text(monkeypatch)
    # The learner picked a different length than the suggestion.
    text_response = await client.post(
        "/api/texts",
        json={
            "topic_slug": "daily-life",
            "length": "medium",
            "preset": "easy",
            "suggestion_id": suggestion_id,
        },
    )
    assert text_response.status_code == 201

    row = await session.get(Suggestion, suggestion_id)
    await session.refresh(row)
    assert row.used_text_id is None


async def test_text_without_a_suggestion_id_is_unaffected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _patched_generate_text(monkeypatch)
    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "easy"}
    )
    assert response.status_code == 201


async def test_the_browsers_local_hour_sets_the_time_of_day(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import suggestions as suggestions_api

    seen: list[str] = []

    async def fake_generate_suggestion(*, config, context, valid_topic_slugs):
        seen.append(context.time_of_day)
        return suggestions.SuggestionResult(
            topic_slug="daily-life",
            length="short",  # type: ignore[arg-type]
            preset="easy",  # type: ignore[arg-type]
            overrides=None,
            reason="r",
            usage=CallUsage(prompt_tokens=1, completion_tokens=1, cached_tokens=0),
            model="gpt-4o-mini",
        )

    monkeypatch.setattr(suggestions_api, "generate_suggestion", fake_generate_suggestion)

    response = await client.post("/api/suggestions", json={"local_hour": 21})
    assert response.status_code == 201
    assert seen == [time_of_day_label(21)]

    bad = await client.post("/api/suggestions", json={"local_hour": 25})
    assert bad.status_code == 422
