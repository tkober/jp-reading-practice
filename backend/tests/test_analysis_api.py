"""`POST /api/analysis` (issue #7) -- reuses `test_kanji_trainer.py`'s fake
MCP server, same pattern as `test_kanji_trainer_status.py`."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app import kanji_trainer as kt
from tests.test_kanji_trainer import _build_app, _free_port, _running, _State


@pytest.fixture(autouse=True)
def _clear_kanji_trainer_cache() -> None:
    kt.clear_cache()
    yield
    kt.clear_cache()


async def test_analyzes_with_the_live_known_set_and_jlpt_levels(client: AsyncClient) -> None:
    """The fake server's `get_jlpt_levels` always answers level 5 and its
    known lists are 水 (kanji) and 水曜日 (vocabulary) -- see `_State`'s
    fixtures in `test_kanji_trainer.py`. 水 should come back known; a kanji
    the fake does not know (木) should not."""
    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

        response = await client.post("/api/analysis", json={"text": "水と木"})

        assert response.status_code == 200
        body = response.json()
        assert body["kanji_trainer_error"] is None

        tokens = body["paragraphs"][0]["tokens"]
        by_surface = {t["surface"]: t for t in tokens}
        assert by_surface["水"]["kanji"][0]["known"] is True
        assert by_surface["水"]["jlpt"] == 5
        assert by_surface["木"]["kanji"][0]["known"] is False


async def test_unavailable_kanji_trainer_still_analyzes_with_an_empty_known_set(
    client: AsyncClient,
) -> None:
    url = f"http://127.0.0.1:{_free_port()}/mcp"
    await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

    response = await client.post("/api/analysis", json={"text": "水"})

    assert response.status_code == 200
    body = response.json()
    assert body["kanji_trainer_error"] is not None
    assert "unreachable" in body["kanji_trainer_error"]

    tokens = body["paragraphs"][0]["tokens"]
    assert tokens[0]["surface"] == "水"
    assert tokens[0]["kanji"][0]["known"] is False
    assert tokens[0]["jlpt"] is None


async def test_response_includes_metrics(client: AsyncClient) -> None:
    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

        response = await client.post("/api/analysis", json={"text": "水を飲む。"})

        assert response.status_code == 200
        metrics = response.json()["metrics"]
        assert metrics["characters"] > 0
        assert metrics["words"] > 0
        assert "jlpt_mix" in metrics
