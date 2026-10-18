"""`app.news`: the material step's RSS and web-search fetchers (issue #15).

RSS/RDF/Atom parsing runs against the fixtures in `tests/fixtures/` served
by a tiny FastAPI app (same `_running_http` pattern as `test_generation.py`'s
fake OpenAI server) -- no real network involved. Dates in the fixtures are
templated (`{channel_date}`/`{fresh_item_date}`/`{stale_item_date}`) and
filled in with real RFC 822 / ISO 8601 strings relative to "now" at test
time, so the freshness window is exercised deterministically rather than
drifting as the fixtures age.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app import news
from app.runtime_config import RuntimeConfig
from tests._server_helpers import _running_http
from tests.test_kanji_trainer import _free_port

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_news_cache() -> None:
    news.clear_cache()
    yield
    news.clear_cache()


def _rfc822(dt: datetime) -> str:
    return format_datetime(dt)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _fill(fixture_name: str, *, date_format: str) -> str:
    """Load a fixture and fill in its three date placeholders: a fresh
    channel date, a fresh item date (1 day old), and a stale one (10 days
    old, outside the 3-day freshness window)."""
    now = datetime.now(timezone.utc)
    fresh = now - timedelta(days=1)
    stale = now - timedelta(days=10)
    fmt = _rfc822 if date_format == "rfc822" else _iso
    template = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    return template.format(
        channel_date=fmt(now), fresh_item_date=fmt(fresh), stale_item_date=fmt(stale)
    )


def _config(*, openai_api_base: str = "http://127.0.0.1:1/v1", web_search_enabled: bool = False) -> RuntimeConfig:
    return RuntimeConfig(
        openai_api_key="sk-test",
        generation_model="gpt-4o-mini",
        help_model="gpt-4o",
        kanji_trainer_mcp_url="http://127.0.0.1:1/mcp",
        web_search_enabled=web_search_enabled,
        openai_api_base=openai_api_base,
    )


# --- RSS 2.0 / RDF / Atom parsing, one format at a time ----------------------


def _build_feed_app(body: str, *, content_type: str = "application/xml") -> FastAPI:
    app = FastAPI()
    request_count = {"n": 0}
    app.state.request_count = request_count

    @app.get("/feed.xml")
    async def feed() -> Response:
        request_count["n"] += 1
        return Response(content=body, media_type=content_type)

    return app


async def test_rss2_items_parsed_with_title_link_summary_date() -> None:
    body = _fill("rss2.xml", date_format="rfc822")
    async with _running_http(_build_feed_app(body), _free_port()) as base_url:
        url = f"{base_url.removesuffix('/v1')}/feed.xml"
        result = await news.fetch_rss_material([url])

    assert result.error is None
    titles = [item.title for item in result.items]
    assert "台風が近づいています" in titles
    # The dateless item is kept (the feed's own `lastBuildDate` is fresh);
    # the explicitly stale item is dropped.
    assert "日付のない記事" in titles
    assert "古い記事" not in titles
    chosen = next(item for item in result.items if item.title == "台風が近づいています")
    assert chosen.link == "https://example.test/news/typhoon"
    assert chosen.summary
    assert chosen.published is not None


async def test_rdf_items_parsed_via_dc_date() -> None:
    body = _fill("rdf.xml", date_format="iso")
    async with _running_http(_build_feed_app(body), _free_port()) as base_url:
        url = f"{base_url.removesuffix('/v1')}/feed.xml"
        result = await news.fetch_rss_material([url])

    assert result.error is None
    titles = [item.title for item in result.items]
    assert "天気予報：週末は晴れ" in titles
    assert "古いニュース" not in titles


async def test_atom_items_parsed_via_entry_and_href_link() -> None:
    body = _fill("atom.xml", date_format="iso")
    async with _running_http(_build_feed_app(body), _free_port()) as base_url:
        url = f"{base_url.removesuffix('/v1')}/feed.xml"
        result = await news.fetch_rss_material([url])

    assert result.error is None
    titles = [item.title for item in result.items]
    assert "新しい電車が導入されます" in titles
    assert "日付のない記事（アトム）" in titles  # kept: the feed's own `updated` is fresh
    assert "古いアトム記事" not in titles
    chosen = next(item for item in result.items if item.title == "新しい電車が導入されます")
    # Atom's own `<link href="...">` attribute, not text content.
    assert chosen.link == "https://example.test/atom/train"


# --- freshness, merging, ordering, redirects, cache --------------------------


async def test_frozen_feed_with_nothing_fresh_reports_the_reason() -> None:
    """The exact issue #15 feed check: every item (and the channel itself)
    is stale -- the whole feed must be treated as having nothing, not
    silently feeding two-month-old headlines into the prompt."""
    now = datetime.now(timezone.utc)
    frozen_date = now - timedelta(days=60)
    body = (FIXTURES / "rss2.xml").read_text(encoding="utf-8").format(
        channel_date=_rfc822(frozen_date),
        fresh_item_date=_rfc822(frozen_date),
        stale_item_date=_rfc822(frozen_date),
    )
    async with _running_http(_build_feed_app(body), _free_port()) as base_url:
        url = f"{base_url.removesuffix('/v1')}/feed.xml"
        result = await news.fetch_rss_material([url])

    assert result.items == []
    assert result.error is not None
    assert "no items from the last 3 days" in result.error


async def test_multiple_feeds_merge_newest_first_top_five() -> None:
    now = datetime.now(timezone.utc)

    def _one_item_feed(title: str, age_hours: int) -> str:
        pub = _rfc822(now - timedelta(hours=age_hours))
        return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title><link>https://example.test/</link>
<description>d</description><lastBuildDate>{pub}</lastBuildDate>
<item><title>{title}</title><link>https://example.test/{title}</link>
<description>s</description><pubDate>{pub}</pubDate></item>
</channel></rss>"""

    app = FastAPI()

    @app.get("/a.xml")
    async def feed_a() -> Response:
        return Response(content=_one_item_feed("A1", 1) , media_type="application/xml")

    @app.get("/b.xml")
    async def feed_b() -> Response:
        # Three items via three endpoints is simplest -- re-use the same
        # route for distinct ages.
        return Response(content=_one_item_feed("B1", 50), media_type="application/xml")

    async with _running_http(app, _free_port()) as base_url:
        root = base_url.removesuffix("/v1")
        result = await news.fetch_rss_material([f"{root}/a.xml", f"{root}/b.xml"])

    assert [item.title for item in result.items] == ["A1", "B1"]  # newest (1h) before older (50h)


async def test_redirect_is_followed() -> None:
    body = _fill("rss2.xml", date_format="rfc822")
    app = FastAPI()

    @app.get("/old-location.xml")
    async def old() -> RedirectResponse:
        return RedirectResponse("/new-location.xml")

    @app.get("/new-location.xml")
    async def new() -> Response:
        return Response(content=body, media_type="application/xml")

    async with _running_http(app, _free_port()) as base_url:
        url = f"{base_url.removesuffix('/v1')}/old-location.xml"
        result = await news.fetch_rss_material([url])

    assert result.error is None
    assert result.items


async def test_a_failing_feed_falls_back_but_does_not_break_other_feeds() -> None:
    body = _fill("rss2.xml", date_format="rfc822")
    app = FastAPI()

    @app.get("/ok.xml")
    async def ok() -> Response:
        return Response(content=body, media_type="application/xml")

    async with _running_http(app, _free_port()) as base_url:
        root = base_url.removesuffix("/v1")
        dead_url = f"http://127.0.0.1:{_free_port()}/nope.xml"  # nothing listening there
        result = await news.fetch_rss_material([dead_url, f"{root}/ok.xml"])

    assert result.error is None
    assert result.items  # the live feed's items still came through


async def test_every_feed_down_reports_the_connection_failures() -> None:
    dead_url = f"http://127.0.0.1:{_free_port()}/nope.xml"
    result = await news.fetch_rss_material([dead_url])
    assert result.items == []
    assert result.error is not None
    assert "Could not read the topic's news feed(s)" in result.error


async def test_feed_is_cached_for_the_ttl() -> None:
    body = _fill("rss2.xml", date_format="rfc822")
    app = _build_feed_app(body)
    async with _running_http(app, _free_port()) as base_url:
        url = f"{base_url.removesuffix('/v1')}/feed.xml"
        await news.fetch_rss_material([url])
        await news.fetch_rss_material([url])

    assert app.state.request_count["n"] == 1  # the second call hit the cache


async def test_no_feed_urls_is_a_no_op() -> None:
    result = await news.fetch_rss_material([])
    assert result.items == []
    assert result.error is not None


# --- web search ----------------------------------------------------------------


def _responses_body(*, items: list[dict], prompt_tokens: int = 200, completion_tokens: int = 80) -> dict:
    import json

    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps({"items": items})}],
            }
        ],
        "usage": {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "input_tokens_details": {"cached_tokens": 0},
        },
    }


def _build_responses_app(
    *, body: dict | None = None, status_code: int = 200, error_detail: str = "upstream failure"
) -> tuple[FastAPI, list[dict]]:
    requests: list[dict] = []
    app = FastAPI()

    @app.post("/v1/responses")
    async def responses(request: Request) -> JSONResponse:
        requests.append(await request.json())
        if status_code != 200:
            return JSONResponse(status_code=status_code, content={"error": {"message": error_detail}})
        return JSONResponse(content=body)

    return app, requests


async def test_web_search_request_shape_and_items() -> None:
    body = _responses_body(
        items=[
            {
                "title": "新しいイベント",
                "link": "https://example.test/event",
                "summary": "来月開催されます。",
                "date": "2026-10-17T09:00:00+09:00",
            }
        ]
    )
    app, requests = _build_responses_app(body=body)

    async with _running_http(app, _free_port()) as openai_url:
        config = _config(openai_api_base=openai_url)
        result, usage = await news.fetch_web_search_material(config, "Current events")

    assert result.error is None
    assert len(result.items) == 1
    assert result.items[0].title == "新しいイベント"
    assert result.items[0].link == "https://example.test/event"
    assert usage is not None
    assert usage.prompt_tokens == 200
    assert usage.completion_tokens == 80

    sent = requests[0]
    assert sent["model"] == "gpt-4o-mini"
    assert sent["tools"] == [{"type": "web_search"}]
    assert sent["text"]["format"]["type"] == "json_schema"
    assert "Current events" in sent["input"]


async def test_web_search_no_api_key_is_a_no_op_with_no_usage() -> None:
    config = RuntimeConfig(
        openai_api_key="",
        generation_model="gpt-4o-mini",
        help_model="gpt-4o",
        kanji_trainer_mcp_url="http://127.0.0.1:1/mcp",
        web_search_enabled=True,
        openai_api_base="http://127.0.0.1:1/v1",
    )
    result, usage = await news.fetch_web_search_material(config, "Current events")
    assert result.items == []
    assert result.error is not None
    assert usage is None


async def test_web_search_upstream_error_falls_back_with_usage_still_none() -> None:
    app, _ = _build_responses_app(status_code=500, error_detail="boom")
    async with _running_http(app, _free_port()) as openai_url:
        config = _config(openai_api_base=openai_url)
        result, usage = await news.fetch_web_search_material(config, "Current events")

    assert result.items == []
    assert result.error is not None
    assert usage is None


async def test_web_search_unsupported_model_raises() -> None:
    app, _ = _build_responses_app(
        status_code=400, error_detail="This model does not support the web_search tool."
    )
    async with _running_http(app, _free_port()) as openai_url:
        config = _config(openai_api_base=openai_url)
        with pytest.raises(news.WebSearchUnsupported, match="web search tool"):
            await news.fetch_web_search_material(config, "Current events")


async def test_web_search_empty_items_reports_nothing_current() -> None:
    body = _responses_body(items=[])
    app, _ = _build_responses_app(body=body)
    async with _running_http(app, _free_port()) as openai_url:
        config = _config(openai_api_base=openai_url)
        result, usage = await news.fetch_web_search_material(config, "Current events")

    assert result.items == []
    assert result.error is not None
    assert usage is not None  # the call itself succeeded; it just found nothing
