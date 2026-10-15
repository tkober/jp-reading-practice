"""`GET /api/kanji-trainer/status` -- the Settings screen's connection test.

Reuses `test_kanji_trainer.py`'s fake server so this exercises the real
`RuntimeConfig` -> client -> response path rather than mocking the client
away.
"""

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


async def test_status_reports_reachable_with_counts(client: AsyncClient) -> None:
    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

        response = await client.get("/api/kanji-trainer/status")

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "reachable": True,
            "url": url,
            "level": 12,
            # Lengths of the known lists (the fake serves one item each),
            # not the summary's per-state or JLPT counts.
            "known_kanji": 1,
            "known_vocabulary": 1,
            "error": None,
        }


async def test_status_reports_unreachable_with_an_error_and_still_200(client: AsyncClient) -> None:
    url = f"http://127.0.0.1:{_free_port()}/mcp"
    await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

    response = await client.get("/api/kanji-trainer/status")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["url"] == url
    assert body["level"] is None
    assert body["known_kanji"] is None
    assert body["known_vocabulary"] is None
    assert "unreachable" in body["error"]


async def test_status_bypasses_but_refreshes_the_cache(client: AsyncClient) -> None:
    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

        # Warm the cache with a plain call first.
        await kt.get_learning_summary(url)
        assert state.calls["get_learning_summary"] == 1

        # The status endpoint must still hit the server (a `fresh` call)...
        await client.get("/api/kanji-trainer/status")
        assert state.calls["get_learning_summary"] == 2

        # ...but a plain call right after is a cache hit again, served from
        # what the status endpoint's fresh call just refreshed -- the known
        # lists included, which generation reads next.
        await kt.get_learning_summary(url)
        await kt.get_known_kanji(url)
        await kt.get_known_vocabulary(url)
        assert state.calls["get_learning_summary"] == 2
        assert state.calls["get_known_kanji"] == 1
        assert state.calls["get_known_vocabulary"] == 1


async def test_changing_the_url_clears_the_cache(client: AsyncClient) -> None:
    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        await kt.get_known_kanji(url)
        assert state.calls["get_known_kanji"] == 1

        await client.put("/api/settings", json={"kanji_trainer_mcp_url": url})

        # The PUT must have cleared the cache even though the stored value
        # is the same URL this test already warmed the cache under.
        await kt.get_known_kanji(url)
        assert state.calls["get_known_kanji"] == 2
