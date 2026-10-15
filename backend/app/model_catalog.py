"""Selectable models for the two configurable slots.

The Settings screen offers a dropdown rather than a text field, and the list
behind it is built from two sources that answer different questions, exactly
as in jp-conversation-practice's ``model_catalog.py`` -- this is that module,
reduced to the two chat slots this app actually has.

``GET /v1/models`` answers *what this account may call*. It is authoritative
and always current, but each entry carries only ``id``, ``created``,
``owned_by`` and ``shutdown_date`` -- no price, no modality, no capability.

The curated table below answers *what is worth picking*. That is knowledge
the API does not expose, so it is written down here.

Merging the two keeps both properties: a model released after the last deploy
is still selectable, and the ones we actually know something about come first
with a description. Anything the filters drop can still be typed into the
free-text field the UI keeps as an escape hatch.

No pricing here yet -- unlike jp-conversation-practice's realtime slot, this
app bills nothing per-token today (#... tracked separately if that changes).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# The live list changes on OpenAI's release schedule, not ours, so a short
# cache is plenty and keeps the Settings screen off the network on every open.
_CACHE_TTL_SECONDS = 15 * 60

# Dated ids like `gpt-5-2025-08-07` pin an alias that is already in the list,
# so including them would roughly double every dropdown without adding a
# single capability. Someone who deliberately wants a pinned snapshot types it
# into the free-text field.
_SNAPSHOT_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")

MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def is_valid_model_id(model: str) -> bool:
    """Whether ``model`` is shaped like a model id."""
    return bool(MODEL_ID_PATTERN.fullmatch(model))


@dataclass(frozen=True)
class CuratedModel:
    """A model we have an opinion about.

    `description` is user-facing and therefore English, like the rest of the
    UI copy.
    """

    id: str
    label: str
    description: str


@dataclass(frozen=True)
class ModelSlot:
    """One configurable model, and how to recognise candidates for it.

    `prefixes` / `contains` select from the live list, `excludes` removes the
    ids that match by name but not by purpose.
    """

    key: str
    label: str
    hint: str
    curated: tuple[CuratedModel, ...]
    prefixes: tuple[str, ...] = ()
    contains: tuple[str, ...] = ()
    exact: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()

    def matches(self, model_id: str) -> bool:
        """Whether a live-list id belongs in this slot's dropdown."""
        if any(fragment in model_id for fragment in self.excludes):
            return False
        if _SNAPSHOT_SUFFIX.search(model_id):
            return False
        return (
            model_id in self.exact
            or any(model_id.startswith(prefix) for prefix in self.prefixes)
            or any(fragment in model_id for fragment in self.contains)
        )


# Chat models that can drive Structured Outputs. Shared by both slots: both
# send a normal chat completion, they only differ in what they write.
_CHAT_PREFIXES = ("gpt-5", "gpt-4.1", "gpt-4o", "o3", "o4")
_CHAT_EXCLUDES = (
    "-transcribe",
    "-tts",
    "-audio",
    "-realtime",
    "-search",
    "-image",
    "-codex",
    "-deep-research",
    "-instruct",
)


SLOTS: tuple[ModelSlot, ...] = (
    ModelSlot(
        key="generation",
        label="Text generation",
        hint="Writes the reading practice texts at the learner's level.",
        curated=(
            CuratedModel(
                "gpt-4o-mini", "gpt-4o-mini", "Default. Fast and cheap for generating texts."
            ),
            CuratedModel(
                "gpt-4o", "gpt-4o", "More precise at holding a target vocabulary mix."
            ),
            CuratedModel(
                "gpt-5-mini", "gpt-5-mini", "Newer generation, good value for this task."
            ),
        ),
        prefixes=_CHAT_PREFIXES,
        excludes=_CHAT_EXCLUDES,
    ),
    ModelSlot(
        key="help",
        label="Reading help",
        hint="Answers questions about a text already on screen -- translate, explain, grammar.",
        curated=(
            CuratedModel("gpt-4o", "gpt-4o", "Default. Writes usable explanations."),
            CuratedModel("gpt-5", "gpt-5", "Stronger at grammar explanations."),
            CuratedModel("gpt-4o-mini", "gpt-4o-mini", "Cheaper, terser answers."),
        ),
        prefixes=_CHAT_PREFIXES,
        excludes=_CHAT_EXCLUDES,
    ),
)

SLOTS_BY_KEY = {slot.key: slot for slot in SLOTS}


@dataclass
class ModelOption:
    """One entry in a dropdown."""

    id: str
    label: str
    description: str | None
    curated: bool
    # From the live list: the date after which OpenAI retires the model.
    shutdown_date: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "curated": self.curated,
            "shutdown_date": self.shutdown_date,
        }


@dataclass
class CatalogResult:
    """Every slot's options, plus why the live list may be missing."""

    slots: list[dict[str, object]] = field(default_factory=list)
    live_ok: bool = False
    live_detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "slots": self.slots,
            "live_ok": self.live_ok,
            "live_detail": self.live_detail,
        }


class ModelListError(RuntimeError):
    """Raised when the live model list cannot be fetched."""


class ModelCatalog:
    """Builds the dropdown contents, caching the live list in process."""

    def __init__(self) -> None:
        self._cache: dict[str, str | None] | None = None
        self._cache_time = 0.0
        self._cache_key = ""
        self._lock = asyncio.Lock()

    async def build(self, api_base: str, api_key: str) -> CatalogResult:
        """Curated entries first, live extras after, never failing on network.

        A missing key or an unreachable API degrades to the curated list
        rather than an empty dropdown.
        """
        live: dict[str, str | None] = {}
        detail: str | None = None
        ok = False

        if not api_key:
            detail = "No OpenAI API key is set."
        else:
            try:
                live = await self._live_models(api_base, api_key)
                ok = True
            except ModelListError as exc:
                detail = str(exc)

        result = CatalogResult(live_ok=ok, live_detail=detail)
        for slot in SLOTS:
            result.slots.append(
                {
                    "key": slot.key,
                    "label": slot.label,
                    "hint": slot.hint,
                    "options": [option.as_dict() for option in _options_for(slot, live)],
                }
            )
        return result

    async def _live_models(self, api_base: str, api_key: str) -> dict[str, str | None]:
        """Model ids to shutdown date, cached per key so a new key refetches."""
        cache_key = f"{api_base}\n{api_key}"
        async with self._lock:
            fresh = (
                self._cache is not None
                and self._cache_key == cache_key
                and time.time() - self._cache_time < _CACHE_TTL_SECONDS
            )
            if fresh and self._cache is not None:
                return self._cache

            models = await _fetch_models(api_base, api_key)
            self._cache = models
            self._cache_time = time.time()
            self._cache_key = cache_key
            return models


def _options_for(slot: ModelSlot, live: dict[str, str | None]) -> list[ModelOption]:
    """Curated entries in their hand-picked order, then live extras sorted."""
    options: list[ModelOption] = []
    seen: set[str] = set()

    for entry in slot.curated:
        options.append(ModelOption(entry.id, entry.label, entry.description, True))
        seen.add(entry.id)

    extras = sorted(
        model_id for model_id in live if model_id not in seen and slot.matches(model_id)
    )
    for model_id in extras:
        options.append(ModelOption(model_id, model_id, None, False, shutdown_date=live.get(model_id)))

    return options


async def _fetch_models(api_base: str, api_key: str) -> dict[str, str | None]:
    """Ask the API which models this key may call."""
    url = f"{api_base.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Model list failed: HTTP %s", exc.response.status_code)
        raise ModelListError(
            f"Model list unavailable (HTTP {exc.response.status_code})."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Model list failed: %s", exc)
        raise ModelListError("The OpenAI API is unreachable for the model list.") from exc

    models: dict[str, str | None] = {}
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not is_valid_model_id(model_id):
            continue
        shutdown = entry.get("shutdown_date")
        models[model_id] = shutdown if isinstance(shutdown, str) else None
    return models
