"""Material for topic generation: real current news items fetched before
writing a text, for a topic that has ``feed_urls`` (issue #15).

Two paths, chosen by ``RuntimeConfig.web_search_enabled``:

- **RSS** (default): every feed URL on the topic, fetched concurrently... no,
  sequentially (one small `httpx.AsyncClient`), parsed as RSS 2.0, RDF/RSS
  1.0 or Atom, merged, filtered to the last 3 days, newest first, top
  `MAX_ITEMS`.
- **Web search** (opt-in, the existing Settings toggle): one OpenAI
  Responses API call with the built-in ``web_search`` tool, asking for a
  handful of current Japanese headlines about the topic as structured JSON.

Either path returns a :class:`MaterialResult` -- the same shape regardless
of which one ran, so ``generation.py``'s material step does not need to
know which path produced it. An empty result always carries ``error``
(why), which ``generation.py`` stores as ``material_error`` and folds into
the prompt's fallback line -- the same "degrade with a reason" shape
``kanji_trainer.py``'s ``KanjiTrainerUnavailable`` already established for
the known-kanji set.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree as ET

from .pricing import CallUsage
from .runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

#: Real browser-like UA -- NHK (and most Japanese news sites) answer a bare
#: `python-httpx/...` UA with a 403 or an empty body.
FEED_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
FEED_TIMEOUT_SECONDS = 10.0
#: An item (or, lacking its own date, a whole feed) older than this is
#: dropped -- a feed that has frozen (stopped publishing) must not silently
#: feed two-month-old headlines into a text (the issue #15 feed check).
FRESHNESS_WINDOW = timedelta(days=3)
MAX_ITEMS = 5
CACHE_TTL_SECONDS = 15 * 60

#: 3-5 items, per the brief; the Responses API call itself asks for exactly
#: this range.
WEB_SEARCH_MIN_ITEMS = 3
WEB_SEARCH_MAX_ITEMS = 5


@dataclass(frozen=True)
class NewsItem:
    """One material item, however it was found."""

    title: str
    link: str
    summary: str
    published: datetime | None

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "published": self.published.isoformat() if self.published else None,
        }


@dataclass(frozen=True)
class MaterialResult:
    """What one material fetch produced. ``error`` is set exactly when
    ``items`` is empty -- "nothing fresh" and "the feed/call failed outright"
    both end up here with their own English reason; the caller never has to
    tell them apart, only report the reason and fall back."""

    items: list[NewsItem]
    error: str | None


# --- RSS / RDF / Atom ---------------------------------------------------------

#: `(fetched_at, (items, the feed's own channel/feed-level date))`, keyed by
#: URL -- a deliberately small cache, not persisted, since the feed URL set
#: is tiny (one topic, usually one feed) and a restart losing it costs
#: nothing.
_feed_cache: dict[str, tuple[float, tuple[list[NewsItem], datetime | None]]] = {}


def clear_cache() -> None:
    """Drop every cached feed -- for tests, and symmetry with
    `kanji_trainer.clear_cache()`."""
    _feed_cache.clear()


def _cache_get(url: str) -> tuple[list[NewsItem], datetime | None] | None:
    entry = _feed_cache.get(url)
    if entry is None:
        return None
    fetched_at, value = entry
    if time.monotonic() - fetched_at > CACHE_TTL_SECONDS:
        return None
    return value


def _cache_set(url: str, value: tuple[list[NewsItem], datetime | None]) -> None:
    _feed_cache[url] = (time.monotonic(), value)


def _parse_date(value: str | None) -> datetime | None:
    """RFC 822 (`pubDate`) first, then ISO 8601 (`dc:date`/Atom
    `updated`/`published`) -- the two date shapes the three feed formats
    use."""
    if not value:
        return None
    value = value.strip()
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _local(tag: str) -> str:
    """Strip a `{namespace}` prefix -- RSS 2.0 has none, RDF/Atom do, and
    matching by local name alone is enough to handle all three with one
    pass (they differ in element names, not in overall shape)."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(el: object, *names: str) -> str | None:
    """The text of the first direct child of `el` whose local name is one
    of `names` -- never a nested descendant (so a channel-level date is
    never confused with an item's own)."""
    wanted = set(names)
    for child in el:  # type: ignore[attr-defined]
        if _local(child.tag) in wanted and child.text:
            return child.text.strip()
    return None


def _atom_link(entry: object) -> str:
    """Atom's `<link href="...">` carries the URL as an attribute, not text
    -- RSS/RDF's `<link>` is a plain text element."""
    for child in entry:  # type: ignore[attr-defined]
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if href:
            return href
        if child.text:
            return child.text.strip()
    return ""


def _parse_feed_items(root: object) -> list[NewsItem]:
    """Every `<item>` (RSS 2.0, RDF/RSS 1.0) or `<entry>` (Atom), anywhere
    in the tree, regardless of namespace."""
    items: list[NewsItem] = []
    for el in root.iter():  # type: ignore[attr-defined]
        local = _local(el.tag)
        if local == "item":
            items.append(
                NewsItem(
                    title=_child_text(el, "title") or "",
                    link=_child_text(el, "link") or "",
                    summary=_child_text(el, "description", "summary") or "",
                    published=_parse_date(_child_text(el, "pubDate", "date")),
                )
            )
        elif local == "entry":
            items.append(
                NewsItem(
                    title=_child_text(el, "title") or "",
                    link=_atom_link(el),
                    summary=_child_text(el, "summary", "content") or "",
                    published=_parse_date(_child_text(el, "published", "updated")),
                )
            )
    return items


def _feed_own_date(root: object) -> datetime | None:
    """The feed/channel-level date -- RSS 2.0's `channel/lastBuildDate` (or
    `pubDate`), RDF's `channel/dc:date`, Atom's `feed/updated` -- used only
    as the fallback freshness signal for an item with no date of its own.

    RSS 2.0 and RDF both have a `channel` child to look inside; Atom has
    none, so the search falls back to the root (`<feed>`) element itself.
    Either way this only reads *direct* children, never an item's/entry's
    own same-named date.
    """
    channel = None
    for child in root:  # type: ignore[attr-defined]
        if _local(child.tag) == "channel":
            channel = child
            break
    scope = channel if channel is not None else root
    return _parse_date(_child_text(scope, "lastBuildDate", "pubDate", "updated", "date"))


async def _fetch_one_feed(
    client: httpx.AsyncClient, url: str
) -> tuple[list[NewsItem], datetime | None]:
    cached = _cache_get(url)
    if cached is not None:
        return cached
    response = await client.get(url)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    result = (_parse_feed_items(root), _feed_own_date(root))
    _cache_set(url, result)
    return result


async def fetch_rss_material(feed_urls: list[str]) -> MaterialResult:
    """Fetch every feed, merge, filter to the last `FRESHNESS_WINDOW`, and
    return the newest `MAX_ITEMS`, newest first.

    One feed failing (down, 403, malformed XML) does not fail the others --
    `error` is only set when *nothing* fresh came back at all, naming
    whichever is more informative: the fetch failures, or "nothing is fresh"
    when every feed answered but had nothing recent (the frozen-feed case
    this issue's own feed check found).
    """
    now = datetime.now(timezone.utc)
    collected: list[tuple[datetime, NewsItem]] = []
    fetch_errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=FEED_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": FEED_USER_AGENT},
    ) as client:
        for url in feed_urls:
            try:
                items, own_date = await _fetch_one_feed(client, url)
            except Exception as exc:  # noqa: BLE001 - one bad feed must not break the rest
                logger.warning("Could not read feed %s: %s", url, exc)
                fetch_errors.append(f"{url} ({exc})")
                continue
            for item in items:
                effective = item.published or own_date
                if effective is None:
                    continue
                effective = _as_aware(effective)
                if now - effective > FRESHNESS_WINDOW:
                    continue
                collected.append((effective, item))

    collected.sort(key=lambda pair: pair[0], reverse=True)
    fresh_items = [item for _, item in collected[:MAX_ITEMS]]
    if fresh_items:
        return MaterialResult(items=fresh_items, error=None)

    if fetch_errors:
        return MaterialResult(
            items=[], error="Could not read the topic's news feed(s): " + "; ".join(fetch_errors)
        )
    return MaterialResult(
        items=[], error="The topic's news feed(s) have no items from the last 3 days."
    )


# --- Web search (opt-in) -------------------------------------------------------

#: The Responses API's `text.format` JSON schema for the material call --
#: hand-written (small enough not to need `generation._strict_schema`'s
#: Pydantic round trip).
_WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "link": {"type": "string"},
                    "summary": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["title", "link", "summary", "date"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _extract_output_text(body: dict) -> str | None:
    """The structured JSON text out of a Responses API body -- it rides in
    the `message` output item's `output_text` content, same place citations
    (`annotations`) would, which this does not need: `source_index` in the
    generation schema is how the chosen item's own link reaches the stored
    `source` instead of reading a citation back out."""
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    return None


def _usage_from_responses(body: dict) -> CallUsage:
    """Same `CallUsage` shape as chat completions, from the Responses API's
    own field names (`input_tokens`/`output_tokens`/
    `input_tokens_details.cached_tokens` -- checked against
    https://developers.openai.com/api/docs/api-reference/responses/object,
    2026-10-18)."""
    usage = body.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    return CallUsage(
        prompt_tokens=int(usage.get("input_tokens") or 0),
        completion_tokens=int(usage.get("output_tokens") or 0),
        cached_tokens=int(details.get("cached_tokens") or 0),
    )


class WebSearchUnsupported(RuntimeError):
    """The configured generation model does not support the `web_search`
    tool on the Responses API."""


async def fetch_web_search_material(
    config: RuntimeConfig, topic_title: str
) -> tuple[MaterialResult, CallUsage | None]:
    """One OpenAI Responses API call (`POST /responses`) with the built-in
    `web_search` tool, asking for `WEB_SEARCH_MIN_ITEMS`-`WEB_SEARCH_MAX_ITEMS`
    current Japanese news items about `topic_title`, as structured JSON --
    the opt-in alternative to `fetch_rss_material` (brief: "for news-backed
    topics, instead of RSS, one ... Responses API call ... asking for 3-5
    current Japanese news items").

    Raises nothing: every failure (no key, upstream error, a model that
    does not support the tool, unusable output) becomes the returned
    `MaterialResult.error`, same convention as the RSS path -- except that
    the model-does-not-support-the-tool case is raised as
    `WebSearchUnsupported` instead, since `generation.py` reports that one
    distinctly (brief: "if that model does not support the tool, say so in
    the error") rather than silently falling back to the no-material
    prompt line the way every other material failure does.

    Returns `(result, usage)` -- `usage` is `None` only when the call never
    reached the API at all (no key); every other outcome, including a
    failure, still carries whatever the API billed for that one call, which
    `generation.py` adds to the text's own `usage`/`cost_usd`.
    """
    if not config.openai_api_key:
        return MaterialResult(items=[], error="No OpenAI API key is configured."), None

    payload = {
        "model": config.generation_model,
        "tools": [{"type": "web_search"}],
        "input": (
            f"Find {WEB_SEARCH_MIN_ITEMS} to {WEB_SEARCH_MAX_ITEMS} current Japanese news "
            f'items relevant to the topic "{topic_title}". For each item, give its headline '
            "in Japanese, its article URL, a one-line Japanese summary, and its publication "
            "date (ISO 8601 if you can tell it). Only real, currently published items -- "
            "never invent one."
        ),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "news_material",
                "schema": _WEB_SEARCH_SCHEMA,
                "strict": True,
            }
        },
    }
    url = f"{config.openai_api_base.rstrip('/')}/responses"
    headers = {"Authorization": f"Bearer {config.openai_api_key}"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        if exc.response.status_code in (400, 404) and "web_search" in detail.lower():
            raise WebSearchUnsupported(
                f"{config.generation_model} does not support the web search tool: {detail}"
            ) from exc
        return (
            MaterialResult(
                items=[], error=f"The web search call returned HTTP {exc.response.status_code}: {detail}"
            ),
            None,
        )
    except httpx.HTTPError as exc:
        return MaterialResult(items=[], error=f"Could not reach the OpenAI API for web search: {exc}"), None

    usage = _usage_from_responses(body)
    text = _extract_output_text(body)
    if not text:
        return MaterialResult(items=[], error="The web search call returned no items."), usage

    try:
        parsed = json.loads(text)
        raw_items = parsed.get("items") or []
    except (json.JSONDecodeError, AttributeError):
        return MaterialResult(items=[], error="The web search call returned unusable JSON."), usage

    items = [
        NewsItem(
            title=str(raw.get("title") or "").strip(),
            link=str(raw.get("link") or "").strip(),
            summary=str(raw.get("summary") or "").strip(),
            published=_parse_date(raw.get("date")),
        )
        for raw in raw_items
        if str(raw.get("title") or "").strip()
    ][:WEB_SEARCH_MAX_ITEMS]

    if not items:
        return (
            MaterialResult(items=[], error="The web search found nothing current for this topic."),
            usage,
        )
    return MaterialResult(items=items, error=None), usage
