"""`POST /api/texts` / `GET /api/texts/{id}` wiring (issue #8).

The generation call itself is exercised against a fake OpenAI server in
`test_generation.py`; here `app.api.texts.generate_text` is monkeypatched so
these only check the HTTP layer: topic resolution, error-status mapping,
storage, and that `answer_index` never reaches the response.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.analysis import analyze
from app.generation import GeneratedQuestion, GenerationError, GenerationOutcome
from app.known_set import KnownSet
from app.pricing import CallUsage


def _fake_outcome(**overrides: object) -> GenerationOutcome:
    analysis = analyze("水を飲みます。猫がいます。", KnownSet(), {})
    defaults: dict[str, object] = dict(
        title="水曜日",
        body="水を飲みます。猫がいます。",
        questions=[
            GeneratedQuestion(
                question="What did they drink?",
                options=["Water", "Tea", "Milk", "Juice"],
                answer_index=0,
            ),
            GeneratedQuestion(
                question="What animal is there?",
                options=["Dog", "Cat", "Bird", "Fish"],
                answer_index=1,
            ),
        ],
        text_analysis=analysis,
        attempts=1,
        calls=[CallUsage(prompt_tokens=100, completion_tokens=50, cached_tokens=0)],
        model="gpt-4o-mini",
        kanji_trainer_error=None,
        known_snapshot={
            "level": 12,
            "known_kanji_count": 0,
            "known_vocabulary_count": 0,
            "kanji_trainer_error": None,
        },
    )
    defaults.update(overrides)
    return GenerationOutcome(**defaults)  # type: ignore[arg-type]


async def test_post_texts_stores_and_returns_the_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import texts as texts_api

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "easy"}
    )
    assert response.status_code == 201
    body = response.json()

    assert body["title"] == "水曜日"
    assert len(body["questions"]) == 2
    # `answer_index` must never reach the browser (brief for issue #8).
    for question in body["questions"]:
        assert "answer_index" not in question
    assert body["targets"]["topic_slug"] == "daily-life"
    assert body["targets"]["preset"] == "easy"
    assert body["attempts"] == 1
    assert body["model"] == "gpt-4o-mini"
    # No curated chat model has a rate in pricing.py yet (see pricing.py's
    # own docstring) -- cost is null rather than a guessed number.
    assert body["cost_usd"] is None

    get_response = await client.get(f"/api/texts/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == body


async def test_surprise_resolves_to_a_real_topic(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import texts as texts_api

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts", json={"topic_slug": "surprise", "length": "short", "preset": "easy"}
    )
    assert response.status_code == 201
    body = response.json()
    # Resolved to one of the seven seeded built-ins, never the literal
    # "surprise" sentinel.
    assert body["targets"]["topic_slug"] != "surprise"


async def test_unknown_topic_is_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/texts", json={"topic_slug": "no-such-topic", "length": "short", "preset": "easy"}
    )
    assert response.status_code == 404


async def test_no_api_key_is_409(client: AsyncClient) -> None:
    # The fixtures start with no OPENAI_API_KEY set, so this reaches the
    # real `generate_text()` and fails fast before any network call.
    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "easy"}
    )
    assert response.status_code == 409
    assert "OpenAI API key" in response.json()["detail"]


async def test_upstream_error_is_502(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import texts as texts_api

    async def failing_generate_text(**kwargs: object) -> GenerationOutcome:
        raise GenerationError("The OpenAI API returned HTTP 500: boom", status=502)

    monkeypatch.setattr(texts_api, "generate_text", failing_generate_text)

    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "easy"}
    )
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


async def test_get_unknown_text_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/texts/999999")
    assert response.status_code == 404
