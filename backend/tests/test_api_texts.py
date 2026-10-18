"""`POST /api/texts` / `GET /api/texts/{id}` wiring (issue #8).

The generation call itself is exercised against a fake OpenAI server in
`test_generation.py`; here `app.api.texts.generate_text` is monkeypatched so
these only check the HTTP layer: topic resolution, error-status mapping,
storage, and that `answer_index` never reaches the response.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
    # gpt-4o-mini has a known rate (pricing.py) -- 100 prompt + 50 completion
    # tokens, no cached tokens: 100*0.15 + 50*0.60, per 1M.
    assert body["cost_usd"] == pytest.approx((100 * 0.15 + 50 * 0.60) / 1_000_000)

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


# --- Stretch's adaptive difficulty (issue #13) -------------------------------


async def test_stretch_generation_uses_the_static_default_with_no_adjustments(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import texts as texts_api

    calls: list[dict] = []

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        calls.append(kwargs)
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "stretch"}
    )
    assert response.status_code == 201
    body = response.json()

    assert body["targets"]["unknown_kanji_target"] == pytest.approx(0.05)
    assert body["targets"]["jlpt_mix"]["n3"] == pytest.approx(0.15)
    assert calls[0]["unknown_kanji_target"] == pytest.approx(0.05)
    assert calls[0]["jlpt_mix"].n3 == pytest.approx(0.15)


async def test_stretch_generation_picks_up_the_current_d(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    from app.api import texts as texts_api
    from app.db import GeneratedText, ReadingSession, StretchAdjustment

    # A finished session + one adjustment row moving d to 1.2.
    text_row = GeneratedText(
        topic_id=None,
        params={"topic_slug": "daily-life", "length": "short", "preset": "stretch"},
        title="水",
        body="水",
        questions=[],
        analysis={"paragraphs": [], "metrics": {"characters": 0, "words": 0, "kanji_total": 0, "kanji_unknown": 0, "unknown_kanji_share": 0.0}},
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
    session.add(
        StretchAdjustment(
            session_id=session_row.id,
            d_before=1.0,
            d_after=1.2,
            helps_per_100_words=2.0,
            comprehension=90.0,
            reason="harder",
        )
    )
    await session.commit()

    calls: list[dict] = []

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        calls.append(kwargs)
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "stretch"}
    )
    assert response.status_code == 201
    body = response.json()

    # d=1.2: 20% of the way from anchor 1 (5%) to anchor 2 (10%) -> 6%.
    assert body["targets"]["unknown_kanji_target"] == pytest.approx(0.06)
    assert calls[0]["unknown_kanji_target"] == pytest.approx(0.06)


async def test_stretch_overrides_still_win_over_the_resolved_values(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import texts as texts_api

    calls: list[dict] = []

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        calls.append(kwargs)
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts",
        json={
            "topic_slug": "daily-life",
            "length": "short",
            "preset": "stretch",
            "overrides": {"unknown_kanji_target": 0.08},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["targets"]["unknown_kanji_target"] == pytest.approx(0.08)
    assert calls[0]["unknown_kanji_target"] == pytest.approx(0.08)


async def test_stretch_text_params_record_d_and_which_overrides_were_used(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    from app.api import texts as texts_api
    from app.db import GeneratedText

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts",
        json={
            "topic_slug": "daily-life",
            "length": "short",
            "preset": "stretch",
            "overrides": {"jlpt_mix": {"n5": 1.0}},
        },
    )
    assert response.status_code == 201
    text_id = response.json()["id"]

    row = await session.get(GeneratedText, text_id)
    assert row is not None
    assert row.params["stretch_d"] == pytest.approx(1.0)
    assert row.params["overrides_used"] == {"unknown_kanji_target": False, "jlpt_mix": True}


async def test_easy_text_params_have_no_overrides_used_either(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    """Non-stretch presets never carry `stretch_d`, but still record
    `overrides_used` -- `api/sessions.py`'s qualifying check reads it
    regardless of preset (it checks the preset itself first)."""
    from app.api import texts as texts_api
    from app.db import GeneratedText

    async def fake_generate_text(**kwargs: object) -> GenerationOutcome:
        return _fake_outcome()

    monkeypatch.setattr(texts_api, "generate_text", fake_generate_text)

    response = await client.post(
        "/api/texts", json={"topic_slug": "daily-life", "length": "short", "preset": "easy"}
    )
    text_id = response.json()["id"]

    row = await session.get(GeneratedText, text_id)
    assert row is not None
    assert "stretch_d" not in row.params
    assert row.params["overrides_used"] == {"unknown_kanji_target": False, "jlpt_mix": False}
