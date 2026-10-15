"""`app.kanji_trainer`, the MCP client for kanji-trainer's read-only server.

A fake MCP server -- FastMCP 1.x, the same tool names and return shapes as
kanji-trainer's own `app/mcp_server.py` -- runs on a local port per test, so
these exercise the real Streamable HTTP transport rather than mocking it
away. `_FakeServer` is a thin async context manager around a background
uvicorn thread; `_State` is what each test's tool implementations read from
and write call counters into, so a test can assert "the server was asked
once" (caching) or "the server was asked for at most 2000 items" (batching)
without the client exposing any of that itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app import kanji_trainer as kt


@pytest.fixture(autouse=True)
def _clear_kanji_trainer_cache() -> None:
    """Every test starts from an empty cache and leaves one behind."""
    kt.clear_cache()
    yield
    kt.clear_cache()


# --- fake server --------------------------------------------------------


@dataclass
class _State:
    """What a fake server's tools read from / record into."""

    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    lookup_requests: list[list[str]] = field(default_factory=list)
    jlpt_batch_sizes: list[int] = field(default_factory=list)
    max_jlpt_items: int = 2000
    fail_known_kanji: bool = False
    slow_known_kanji_seconds: float | None = None


_KANJI = kt.KnownItem(
    characters="水",
    slug="water",
    object_type="kanji",
    level=1,
    state="known",
    srs_stage=9,
    meanings=[kt.MeaningOut(meaning="water", primary=True)],
    readings=[kt.ReadingOut(reading="みず", primary=True, type="kunyomi")],
    jlpt=5,
)
_VOCAB = kt.KnownItem(
    characters="水曜日",
    slug="wednesday",
    object_type="vocabulary",
    level=2,
    state="known",
    srs_stage=9,
    meanings=[kt.MeaningOut(meaning="Wednesday", primary=True)],
    readings=[kt.ReadingOut(reading="すいようび", primary=True, type=None)],
    jlpt=5,
)


def _build_app(state: _State, allowed_hosts: list[str] | None = None) -> FastMCP:
    mcp = FastMCP(
        "fake-kanji-trainer",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts)
        if allowed_hosts is not None
        else None,
    )

    @mcp.tool()
    async def get_known_kanji(min_srs_stage: int = 5) -> list[kt.KnownItem]:
        state.calls["get_known_kanji"] += 1
        if state.fail_known_kanji:
            raise ValueError("boom: kanji-trainer could not load progress")
        if state.slow_known_kanji_seconds is not None:
            await asyncio.sleep(state.slow_known_kanji_seconds)
        return [_KANJI]

    @mcp.tool()
    async def get_known_vocabulary(min_srs_stage: int = 5) -> list[kt.KnownItem]:
        state.calls["get_known_vocabulary"] += 1
        return [_VOCAB]

    @mcp.tool()
    async def get_learning_summary() -> kt.LearningSummary:
        state.calls["get_learning_summary"] += 1
        return kt.LearningSummary(
            current_level=12,
            counts={
                "kanji": kt.StateCounts(known=340, learning=10, new=5, suspended=0),
                "vocabulary": kt.StateCounts(known=1200, learning=20, new=15, suspended=0),
            },
            jlpt={
                5: kt.JlptLevelSummary(
                    kanji=kt.JlptLevelCounts(total=100, known=80),
                    vocabulary=kt.JlptLevelCounts(total=300, known=250),
                ),
                4: kt.JlptLevelSummary(
                    kanji=kt.JlptLevelCounts(total=50, known=20),
                    vocabulary=kt.JlptLevelCounts(total=150, known=60),
                ),
                3: kt.JlptLevelSummary(),
                2: kt.JlptLevelSummary(),
                1: kt.JlptLevelSummary(),
            },
        )

    @mcp.tool()
    async def lookup_items(characters: list[str]) -> list[kt.LookupResult]:
        state.calls["lookup_items"] += 1
        state.lookup_requests.append(list(characters))
        return [
            kt.LookupResult(
                characters=characters_query,
                found=True,
                matches=[
                    kt.LookupMatch(
                        object_type="kanji",
                        level=1,
                        state="known",
                        srs_stage=9,
                        known=True,
                        primary_meaning="water",
                        primary_reading="みず",
                        jlpt=5,
                    )
                ],
            )
            for characters_query in characters
        ]

    @mcp.tool()
    async def get_jlpt_levels(items: list[kt.JlptQuery]) -> list[kt.JlptLevelResult]:
        state.calls["get_jlpt_levels"] += 1
        state.jlpt_batch_sizes.append(len(items))
        if len(items) > state.max_jlpt_items:
            raise ValueError(
                f"get_jlpt_levels takes at most {state.max_jlpt_items} items per call, got {len(items)}."
            )
        return [
            kt.JlptLevelResult(
                text=item.text,
                reading=item.reading,
                jlpt=5,
                kanji=[kt.KanjiCharacterLevel(character=ch, jlpt=5) for ch in item.text],
            )
            for item in items
        ]

    return mcp


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.asynccontextmanager
async def _running(mcp: FastMCP, port: int) -> AsyncIterator[str]:
    """Serve `mcp`'s Streamable HTTP app on `port` in a background thread
    for the duration of the block, yielding its `/mcp` URL."""
    app = mcp.streamable_http_app()
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
            raise RuntimeError("fake kanji-trainer server did not start in time")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest_asyncio.fixture
async def fake_server() -> AsyncIterator[tuple[str, _State]]:
    state = _State()
    async with _running(_build_app(state), _free_port()) as url:
        yield url, state


# --- typed parsing ---------------------------------------------------------


async def test_get_known_kanji_parses_typed_items(fake_server: tuple[str, _State]) -> None:
    url, _state = fake_server

    items = await kt.get_known_kanji(url)

    assert items == [_KANJI]


async def test_get_known_vocabulary_parses_typed_items(fake_server: tuple[str, _State]) -> None:
    url, _state = fake_server

    items = await kt.get_known_vocabulary(url)

    assert items == [_VOCAB]


async def test_get_learning_summary_parses_the_jlpt_breakdown(fake_server: tuple[str, _State]) -> None:
    url, _state = fake_server

    summary = await kt.get_learning_summary(url)

    assert summary.current_level == 12
    assert summary.counts["kanji"].known == 340
    assert summary.jlpt[5].kanji.known == 80
    assert summary.jlpt[5].vocabulary.known == 250
    # Keys come back from JSON as strings; validation must coerce them to int.
    assert set(summary.jlpt) == {5, 4, 3, 2, 1}


async def test_lookup_items_parses_results_in_request_order(fake_server: tuple[str, _State]) -> None:
    url, _state = fake_server

    results = await kt.lookup_items(url, ["水", "火"])

    assert [r.characters for r in results] == ["水", "火"]
    assert results[0].found is True
    assert results[0].matches[0].primary_meaning == "water"


async def test_get_jlpt_levels_parses_typed_results(fake_server: tuple[str, _State]) -> None:
    url, _state = fake_server

    results = await kt.get_jlpt_levels(url, [kt.JlptQuery(text="水曜日", reading="すいようび")])

    assert results[0].text == "水曜日"
    assert results[0].jlpt == 5
    assert [k.character for k in results[0].kanji] == ["水", "曜", "日"]


# --- caching -----------------------------------------------------------------


async def test_known_kanji_is_cached_until_cleared(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server

    await kt.get_known_kanji(url)
    await kt.get_known_kanji(url)
    assert state.calls["get_known_kanji"] == 1

    kt.clear_cache()
    await kt.get_known_kanji(url)
    assert state.calls["get_known_kanji"] == 2


async def test_known_kanji_cache_is_keyed_by_min_srs_stage(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server

    await kt.get_known_kanji(url, min_srs_stage=5)
    await kt.get_known_kanji(url, min_srs_stage=1)

    assert state.calls["get_known_kanji"] == 2


async def test_learning_summary_is_cached(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server

    await kt.get_learning_summary(url)
    await kt.get_learning_summary(url)

    assert state.calls["get_learning_summary"] == 1


async def test_status_style_fresh_call_bypasses_but_refills_the_cache(
    fake_server: tuple[str, _State],
) -> None:
    url, state = fake_server

    await kt.get_learning_summary(url)
    assert state.calls["get_learning_summary"] == 1

    await kt.get_learning_summary(url, fresh=True)
    assert state.calls["get_learning_summary"] == 2

    # The fresh call still refreshed the cache, so the next plain call is a hit.
    await kt.get_learning_summary(url)
    assert state.calls["get_learning_summary"] == 2


async def test_lookup_items_caches_per_string_and_dedupes_within_one_call(
    fake_server: tuple[str, _State],
) -> None:
    url, state = fake_server

    # "水" twice in one call must only be asked for once.
    await kt.lookup_items(url, ["水", "水", "火"])
    assert state.calls["lookup_items"] == 1
    assert sorted(state.lookup_requests[0]) == sorted(["火", "水"])

    # Already cached, so a second call never reaches the server.
    await kt.lookup_items(url, ["水", "火"])
    assert state.calls["lookup_items"] == 1

    # A new string still has to be fetched.
    await kt.lookup_items(url, ["木"])
    assert state.calls["lookup_items"] == 2


async def test_get_jlpt_levels_caches_per_text_reading_pair(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server

    await kt.get_jlpt_levels(url, [kt.JlptQuery(text="水"), kt.JlptQuery(text="水", reading="みず")])
    assert state.calls["get_jlpt_levels"] == 1
    assert state.jlpt_batch_sizes[-1] == 2  # distinct: (水, None) and (水, みず)

    await kt.get_jlpt_levels(url, [kt.JlptQuery(text="水")])
    assert state.calls["get_jlpt_levels"] == 1


async def test_clear_cache_clears_lookup_and_jlpt_caches_too(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server

    await kt.lookup_items(url, ["水"])
    await kt.get_jlpt_levels(url, [kt.JlptQuery(text="水")])
    kt.clear_cache()

    await kt.lookup_items(url, ["水"])
    await kt.get_jlpt_levels(url, [kt.JlptQuery(text="水")])

    assert state.calls["lookup_items"] == 2
    assert state.calls["get_jlpt_levels"] == 2


# --- batching over the server's 2000-item cap --------------------------------


async def test_get_jlpt_levels_batches_over_the_server_cap(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server
    state.max_jlpt_items = 2000

    queries = [kt.JlptQuery(text=f"word{i}") for i in range(2500)]
    results = await kt.get_jlpt_levels(url, queries)

    assert len(results) == 2500
    assert {r.text for r in results} == {f"word{i}" for i in range(2500)}
    # Every batch respected the server's cap, and more than one batch was sent.
    assert all(size <= 2000 for size in state.jlpt_batch_sizes)
    assert len(state.jlpt_batch_sizes) == 2
    assert sum(state.jlpt_batch_sizes) == 2500


# --- error kinds --------------------------------------------------------------


async def test_unreachable_host_raises_kanji_trainer_unavailable() -> None:
    # Nothing is listening on this port -- guaranteed connection refused.
    url = f"http://127.0.0.1:{_free_port()}/mcp"

    with pytest.raises(kt.KanjiTrainerUnavailable, match="unreachable"):
        await kt.get_known_kanji(url)


async def test_disallowed_host_raises_with_a_421_specific_message() -> None:
    state = _State()
    async with _running(
        _build_app(state, allowed_hosts=["kanji-trainer.invalid"]), _free_port()
    ) as url:
        with pytest.raises(kt.KanjiTrainerUnavailable, match="MCP_ALLOWED_HOSTS"):
            await kt.get_known_kanji(url)


async def test_tool_error_raises_with_the_server_message(fake_server: tuple[str, _State]) -> None:
    url, state = fake_server
    state.fail_known_kanji = True

    with pytest.raises(kt.KanjiTrainerUnavailable, match="boom"):
        await kt.get_known_kanji(url)


async def test_timeout_raises_with_a_timeout_specific_message(
    fake_server: tuple[str, _State], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, state = fake_server
    state.slow_known_kanji_seconds = 1.0
    monkeypatch.setattr(kt, "CONNECT_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(kt, "CALL_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(kt.KanjiTrainerUnavailable, match="did not respond in time"):
        await kt.get_known_kanji(url)


async def test_get_jlpt_levels_over_the_cap_from_the_server_itself_is_an_unavailable_error(
    fake_server: tuple[str, _State],
) -> None:
    """If the server's own cap is ever lower than this module's batch size
    (e.g. a future server release), the resulting tool error still comes back
    as `KanjiTrainerUnavailable`, not an uncaught exception."""
    url, state = fake_server
    state.max_jlpt_items = 1  # pathologically low, to trigger without 2000+ items

    with pytest.raises(kt.KanjiTrainerUnavailable):
        await kt.get_jlpt_levels(url, [kt.JlptQuery(text="水"), kt.JlptQuery(text="火")])
