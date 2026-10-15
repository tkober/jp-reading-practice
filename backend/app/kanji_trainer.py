"""MCP client for kanji-trainer's read-only server (issue #5).

kanji-trainer exposes what this learner already knows -- kanji, vocabulary,
a level/JLPT summary, and JLPT lookups for arbitrary text -- at ``/mcp``
(Streamable HTTP, stateless, JSON responses; see its ``app/mcp_server.py``
and CLAUDE.md "MCP server" section). This module is the one place that talks
to it: one function per tool, typed results mirroring the server's own
Pydantic models (kept in sync by hand -- there is no shared package between
the two repos), and the error handling every caller needs regardless of what
went wrong on the wire.

Every call opens a fresh connection -- the server is ``stateless_http=True``
and reused across many short-lived backend requests, so there is nothing
worth keeping a persistent session open for, and a fresh connection means a
stale one can never be the reason a call fails.

Caching is in-process and deliberately simple: ``get_known_kanji`` /
``get_known_vocabulary`` / ``get_learning_summary`` are the "whole learner
state" calls, cached for :data:`CACHE_TTL_SECONDS` keyed by the URL (and the
``min_srs_stage`` the first two take); ``lookup_items`` / ``get_jlpt_levels``
are "one entry at a time" calls, cached per string with a bounded LRU
(:data:`LOOKUP_CACHE_MAX_ENTRIES`) since a generated text's distinct tokens
can run into the thousands and never expire on their own -- the dictionary a
text's words sit in does not change. :func:`clear_cache` drops all of it;
call it from tests and from the settings ``PUT`` handler whenever
``kanji_trainer_mcp_url`` changes, since a cache entry is keyed by URL and a
stale one under an old URL would otherwise linger until it expires on its
own.

Every failure -- unreachable host, a 421 from kanji-trainer's own
``MCP_ALLOWED_HOSTS`` check, a tool-side error, a timeout -- becomes one
:class:`KanjiTrainerUnavailable` with an English, human-readable message.
Nothing here decides how to degrade; that is a caller's call (pun noted), not
this module's.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: How long a connection attempt may take before giving up.
CONNECT_TIMEOUT_SECONDS = 5.0
#: How long one tool call may take once connected.
CALL_TIMEOUT_SECONDS = 15.0

#: get_known_kanji/get_known_vocabulary/get_learning_summary -- the "whole
#: learner state" calls -- are cached this long, same default the server
#: itself uses for "known" (Guru I, app.srs.STAGE_GURU_1 there).
CACHE_TTL_SECONDS = 15 * 60
DEFAULT_MIN_SRS_STAGE = 5

#: lookup_items/get_jlpt_levels are cached per string instead, with no TTL --
#: the dictionary a word sits in does not change -- bounded by an LRU so a
#: very long-lived process cannot grow this without limit.
LOOKUP_CACHE_MAX_ENTRIES = 4096

#: get_jlpt_levels' own request cap (app/mcp_server.py's
#: ``_MAX_JLPT_QUERY_ITEMS``); callers here may pass more, so this module
#: batches rather than failing or truncating.
MAX_JLPT_QUERY_ITEMS = 2000


class KanjiTrainerUnavailable(RuntimeError):
    """kanji-trainer's MCP server could not be reached, or it answered with
    an error -- the message is English and safe to show a learner directly.
    """


# --- shapes, mirroring app/mcp_server.py in kanji-trainer -------------------


class MeaningOut(BaseModel):
    meaning: str
    primary: bool = False


class ReadingOut(BaseModel):
    reading: str
    primary: bool = False
    type: str | None = None


class KnownItem(BaseModel):
    """One subject the learner already knows, by kanji-trainer's own
    ``is_known`` rule."""

    characters: str | None
    slug: str
    object_type: str
    level: int
    state: str
    srs_stage: int
    meanings: list[MeaningOut]
    readings: list[ReadingOut]
    #: 5 = N5 (easiest) .. 1 = N1 (hardest), `None` for a radical or a
    #: kanji/word kanji-trainer's checked-in JLPT snapshot does not list.
    jlpt: int | None


class StateCounts(BaseModel):
    new: int = 0
    learning: int = 0
    known: int = 0
    suspended: int = 0


class JlptLevelCounts(BaseModel):
    #: Every subject at this level/type, suspended included.
    total: int = 0
    #: How many of `total` pass `is_known` at the default threshold (Guru I).
    known: int = 0


class JlptLevelSummary(BaseModel):
    kanji: JlptLevelCounts = Field(default_factory=JlptLevelCounts)
    #: `kana_vocabulary` folded in, same grouping kanji-trainer's own
    #: `GET /api/stats/jlpt` uses.
    vocabulary: JlptLevelCounts = Field(default_factory=JlptLevelCounts)


class LearningSummary(BaseModel):
    #: `lowest_open_level()` on kanji-trainer's side -- the same definition
    #: its header counters and `/stats` use. `None` is possible (nothing
    #: imported yet), not just a failure-to-reach marker.
    current_level: int | None
    #: Keyed by object_type ("radical", "kanji", "vocabulary",
    #: "kana_vocabulary").
    counts: dict[str, StateCounts]
    #: Keyed by JLPT level, 5 = N5 .. 1 = N1, every level always present.
    jlpt: dict[int, JlptLevelSummary]


class LookupMatch(BaseModel):
    object_type: str
    level: int
    state: str
    srs_stage: int
    known: bool
    primary_meaning: str | None
    primary_reading: str | None
    jlpt: int | None


class LookupResult(BaseModel):
    characters: str
    found: bool
    matches: list[LookupMatch]


class JlptQuery(BaseModel):
    """One `get_jlpt_levels` request item -- an arbitrary word or kanji."""

    text: str
    #: Narrows a vocabulary match to this reading; without one, the easiest
    #: level among every entry for `text` is used. See kanji-trainer's
    #: `JlptQuery` for the exact folding/stripping rules.
    reading: str | None = None


class KanjiCharacterLevel(BaseModel):
    character: str
    jlpt: int | None


class JlptLevelResult(BaseModel):
    text: str
    reading: str | None
    jlpt: int | None
    kanji: list[KanjiCharacterLevel]


# --- transport ----------------------------------------------------------------


def _leaf_exception(exc: BaseException) -> BaseException:
    """The streamable-http transport runs every request in a task group, so
    a transport failure (a dropped connection, a non-2xx status, a read
    timeout) surfaces as an ``ExceptionGroup`` wrapping the real error rather
    than as that error itself. Unwrap to the first leaf so the message names
    what actually went wrong instead of "unhandled errors in a TaskGroup".
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _unavailable_message(url: str, exc: BaseException) -> str:
    exc = _leaf_exception(exc)

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 421:
            return (
                f"The Kanji Trainer at {url} rejected the request (HTTP 421 "
                "Misdirected Request) -- add this host to MCP_ALLOWED_HOSTS "
                "in the Kanji Trainer."
            )
        return f"The Kanji Trainer at {url} returned HTTP {status}."

    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return f"The Kanji Trainer at {url} did not respond in time."

    if isinstance(exc, (httpx.TransportError, OSError)):
        return f"The Kanji Trainer at {url} is unreachable: {exc}"

    return f"The Kanji Trainer at {url} failed: {exc}"


def _tool_error_message(name: str, result: Any) -> str:
    """The text kanji-trainer's tool error carries, e.g. for a tool that
    raised (the ``get_jlpt_levels`` item cap, among others)."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return f"tool {name!r} failed with no further detail"


async def _call_tool(url: str, name: str, arguments: dict[str, Any]) -> Any:
    """Call one tool and return its structured result (already unwrapped --
    see `_result_list`), raising `KanjiTrainerUnavailable` for every failure
    kind: unreachable, a 421, a timeout, or the tool itself erroring.
    """
    try:
        # A hard cap on the whole call (connect + the call itself), as a
        # backstop in case the transport does not honour its own per-request
        # timeouts cleanly. Reads the module globals at call time (rather
        # than a constant computed once at import), so tests can shrink
        # CONNECT_TIMEOUT_SECONDS/CALL_TIMEOUT_SECONDS and have it follow.
        overall_timeout = CONNECT_TIMEOUT_SECONDS + CALL_TIMEOUT_SECONDS + 5.0
        timeout = httpx.Timeout(CONNECT_TIMEOUT_SECONDS, read=CALL_TIMEOUT_SECONDS)
        async with asyncio.timeout(overall_timeout):
            async with create_mcp_http_client(timeout=timeout) as http_client:
                async with streamable_http_client(url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _get_session_id,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
    except KanjiTrainerUnavailable:
        raise
    except BaseException as exc:  # noqa: BLE001 - every transport failure lands here
        raise KanjiTrainerUnavailable(_unavailable_message(url, exc)) from exc

    if result.isError:
        raise KanjiTrainerUnavailable(
            f"The Kanji Trainer at {url} reported an error calling {name!r}: "
            f"{_tool_error_message(name, result)}"
        )
    return result.structuredContent


def _result_list(structured: Any) -> list[Any]:
    """Unwrap FastMCP's `{"result": [...]}` envelope -- every tool here that
    returns a bare `list[...]` (rather than a model of its own, like
    `get_learning_summary`'s `LearningSummary`) gets wrapped that way because
    a JSON Schema top-level type must be an object."""
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    return structured or []


# --- caching --------------------------------------------------------------


_ttl_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
_lookup_cache: OrderedDict[tuple[str, str], LookupResult] = OrderedDict()
_jlpt_cache: OrderedDict[tuple[str, str, str | None], JlptLevelResult] = OrderedDict()


def clear_cache() -> None:
    """Drop every cached result.

    Call this from tests between cases, and from the settings `PUT` handler
    whenever `kanji_trainer_mcp_url` changes -- entries are keyed by URL, but
    a stale one under an old URL would otherwise sit there until its TTL (or,
    for the LRU caches, forever) rather than being replaced right away.
    """
    _ttl_cache.clear()
    _lookup_cache.clear()
    _jlpt_cache.clear()


async def _ttl_cached(key: tuple[Any, ...], fetch: Callable[[], Awaitable[T]], *, fresh: bool) -> T:
    if not fresh:
        hit = _ttl_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    value = await fetch()
    _ttl_cache[key] = (time.monotonic(), value)
    return value


def _lru_get(cache: OrderedDict[Any, T], key: Any) -> T | None:
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _lru_set(cache: OrderedDict[Any, T], key: Any, value: T) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > LOOKUP_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


# --- tools ------------------------------------------------------------------


async def get_known_kanji(
    url: str, min_srs_stage: int = DEFAULT_MIN_SRS_STAGE, *, fresh: bool = False
) -> list[KnownItem]:
    """Kanji the learner already knows -- see kanji-trainer's own
    `get_known_kanji` for the exact "known" rule."""

    async def fetch() -> list[KnownItem]:
        structured = await _call_tool(url, "get_known_kanji", {"min_srs_stage": min_srs_stage})
        return [KnownItem.model_validate(item) for item in _result_list(structured)]

    return await _ttl_cached(("get_known_kanji", url, min_srs_stage), fetch, fresh=fresh)


async def get_known_vocabulary(
    url: str, min_srs_stage: int = DEFAULT_MIN_SRS_STAGE, *, fresh: bool = False
) -> list[KnownItem]:
    """Vocabulary (incl. kana_vocabulary) the learner already knows."""

    async def fetch() -> list[KnownItem]:
        structured = await _call_tool(url, "get_known_vocabulary", {"min_srs_stage": min_srs_stage})
        return [KnownItem.model_validate(item) for item in _result_list(structured)]

    return await _ttl_cached(("get_known_vocabulary", url, min_srs_stage), fetch, fresh=fresh)


async def get_learning_summary(url: str, *, fresh: bool = False) -> LearningSummary:
    """The learner's level, state counts per object type, and a JLPT
    breakdown. Takes no `min_srs_stage` of its own -- the server bakes the
    default threshold into the `known` counts, same as it does elsewhere."""

    async def fetch() -> LearningSummary:
        structured = await _call_tool(url, "get_learning_summary", {})
        return LearningSummary.model_validate(structured)

    return await _ttl_cached(("get_learning_summary", url), fetch, fresh=fresh)


async def lookup_items(url: str, characters: Sequence[str]) -> list[LookupResult]:
    """Look up specific kanji or words by their exact characters, one result
    per requested string in the same order (duplicates served from the same
    cache entry, same as a single lookup would be).
    """
    if not characters:
        return []

    results: dict[str, LookupResult] = {}
    missing: list[str] = []
    for characters_query in characters:
        cached = _lru_get(_lookup_cache, (url, characters_query))
        if cached is not None:
            results[characters_query] = cached
        else:
            missing.append(characters_query)

    # De-duplicate before the network call -- a text can repeat a word many
    # times, and the server would otherwise do the same lookup over and over.
    unique_missing = list(dict.fromkeys(missing))
    if unique_missing:
        structured = await _call_tool(url, "lookup_items", {"characters": unique_missing})
        fetched = [LookupResult.model_validate(item) for item in _result_list(structured)]
        for characters_query, item in zip(unique_missing, fetched, strict=True):
            _lru_set(_lookup_cache, (url, characters_query), item)
            results[characters_query] = item

    return [results[characters_query] for characters_query in characters]


async def get_jlpt_levels(url: str, items: Sequence[JlptQuery]) -> list[JlptLevelResult]:
    """JLPT levels for arbitrary words and kanji, independent of whether the
    learner's own WaniKani account teaches them.

    Callers may pass more items than the server's own per-call cap
    (`MAX_JLPT_QUERY_ITEMS`, mirroring `_MAX_JLPT_QUERY_ITEMS` there) -- this
    batches rather than failing, after first serving whatever is already
    cached and de-duplicating the rest.
    """
    if not items:
        return []

    results: list[JlptLevelResult | None] = [None] * len(items)
    missing_indices: list[int] = []
    missing_items: list[JlptQuery] = []
    for index, item in enumerate(items):
        cached = _lru_get(_jlpt_cache, (url, item.text, item.reading))
        if cached is not None:
            results[index] = cached
        else:
            missing_indices.append(index)
            missing_items.append(item)

    if missing_items:
        unique_by_key: dict[tuple[str, str | None], JlptQuery] = {
            (item.text, item.reading): item for item in missing_items
        }
        unique_items = list(unique_by_key.values())
        fetched_by_key: dict[tuple[str, str | None], JlptLevelResult] = {}
        for batch_start in range(0, len(unique_items), MAX_JLPT_QUERY_ITEMS):
            batch = unique_items[batch_start : batch_start + MAX_JLPT_QUERY_ITEMS]
            structured = await _call_tool(
                url, "get_jlpt_levels", {"items": [item.model_dump() for item in batch]}
            )
            fetched = [JlptLevelResult.model_validate(item) for item in _result_list(structured)]
            for item, result in zip(batch, fetched, strict=True):
                key = (item.text, item.reading)
                fetched_by_key[key] = result
                _lru_set(_jlpt_cache, (url, *key), result)

        for index, item in zip(missing_indices, missing_items, strict=True):
            results[index] = fetched_by_key[(item.text, item.reading)]

    assert all(result is not None for result in results)  # every index was either a cache hit or just filled
    return results  # type: ignore[return-value]
