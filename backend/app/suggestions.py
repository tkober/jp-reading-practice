"""The AI suggestion for the next text (issue #14): one Structured-Outputs
chat completion against `RuntimeConfig.help_model` (the brief's own choice --
this is a short, prose-adjacent judgement call, the same slot the three LLM
helps and the tutor chat use, not the generation slot), then server-side
validation/clamping of whatever the model returned.

Mirrors `generation.py`'s shape (`_strict_schema`, `_post_chat_completion`/
`_parse_completion`, `GenerationError`'s 409/502 convention) rather than
`assist.py`'s plain-text one: this call needs a forced JSON shape, same as
text generation itself.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from .generation import GenerationError, _strict_schema
from .models import JlptMixTarget, SuggestionOverridesOut
from .pricing import CallUsage, usage_from_response
from .runtime_config import RuntimeConfig
from .suggestion_prompts import SuggestionContext, build_suggestion_prompt

logger = logging.getLogger(__name__)

#: One short call, same margin as the three LLM helps (`assist.TIMEOUT`) --
#: a suggestion is a judgement call over a compact context, not a full text.
TIMEOUT = 60.0

#: The setup screen's own ranges (`setup.types.ts`/`setup-screen.html`'s
#: unknown-kanji slider, `min="0" max="20"`) -- an override outside this is
#: clamped into it, never rejected outright.
UNKNOWN_KANJI_PERCENT_MIN = 0.0
UNKNOWN_KANJI_PERCENT_MAX = 20.0

_MIX_ORDER: tuple[str, ...] = ("n5", "n4", "n3", "n2", "n1")


# --- the model's own structured output --------------------------------------


class SuggestedJlptMixPercent(BaseModel):
    n5: float = 0.0
    n4: float = 0.0
    n3: float = 0.0
    n2: float = 0.0
    n1: float = 0.0


class SuggestedOverrides(BaseModel):
    """The model's raw override guess, in the same percent-space the setup
    screen's own controls use -- `app.suggestions.resolve_overrides` clamps
    and converts this to `SuggestionOverridesOut`'s fraction convention."""

    style: Literal["casual", "polite", "formal"] | None = None
    unknown_kanji_target_percent: float | None = None
    jlpt_mix_percent: SuggestedJlptMixPercent | None = None


class SuggestionSchema(BaseModel):
    """The shape `generate_suggestion()` forces the model into via
    Structured Outputs."""

    topic_slug: str = ""
    length: Literal["short", "medium", "long"] = "medium"
    preset: Literal["easy", "stretch", "challenge"] = "stretch"
    overrides: SuggestedOverrides | None = None
    reason: str = ""


# --- validation/clamping -----------------------------------------------------


def clamp_unknown_kanji_target_percent(value: float) -> float:
    """Clamp to the setup screen's own slider range, rounded to its step
    (1%) -- never dropped, just pulled back into range."""
    return round(max(UNKNOWN_KANJI_PERCENT_MIN, min(UNKNOWN_KANJI_PERCENT_MAX, value)))


def normalize_jlpt_mix_percent(raw: Mapping[str, float]) -> dict[str, float] | None:
    """Round each share to the nearest 5 percentage points and force the
    total to exactly 100 via largest-remainder (N5 first on ties, same tie-
    break `stretch._round_mix_percent` uses) -- `None` ("dropped", per the
    brief) when the input cannot be normalised into a sane mix: any level
    negative, or everything zero (nothing to scale up from).

    Returns fractions (0..1 per level), `JlptMixTarget`'s own convention --
    the caller never has to divide by 100 again.
    """
    values = {level: raw.get(level, 0.0) for level in _MIX_ORDER}
    if any(v < 0 for v in values.values()):
        return None
    total = sum(values.values())
    if total <= 0:
        return None

    scaled = {level: v / total * 100 for level, v in values.items()}
    rounded = {level: round(scaled[level] / 5) * 5 for level in _MIX_ORDER}
    remainder_steps = round((100 - sum(rounded.values())) / 5)
    if remainder_steps:
        ordered = sorted(
            _MIX_ORDER,
            key=lambda level: (
                -(scaled[level] - rounded[level])
                if remainder_steps > 0
                else (scaled[level] - rounded[level]),
                _MIX_ORDER.index(level),
            ),
        )
        for level in ordered[: abs(remainder_steps)]:
            rounded[level] += 5 if remainder_steps > 0 else -5

    if any(v < 0 for v in rounded.values()):
        return None
    return {level: rounded[level] / 100 for level in _MIX_ORDER}


def resolve_overrides(parsed: SuggestedOverrides | None) -> SuggestionOverridesOut | None:
    """Validate/clamp the model's raw overrides into `SuggestionOverridesOut`
    -- `None` when there is nothing left to override at all (either the
    model gave no overrides, or every field it gave was dropped)."""
    if parsed is None:
        return None

    unknown_kanji_target: float | None = None
    if parsed.unknown_kanji_target_percent is not None:
        unknown_kanji_target = clamp_unknown_kanji_target_percent(
            parsed.unknown_kanji_target_percent
        ) / 100

    jlpt_mix: JlptMixTarget | None = None
    if parsed.jlpt_mix_percent is not None:
        normalized = normalize_jlpt_mix_percent(parsed.jlpt_mix_percent.model_dump())
        if normalized is not None:
            jlpt_mix = JlptMixTarget(**normalized)

    if parsed.style is None and unknown_kanji_target is None and jlpt_mix is None:
        return None
    return SuggestionOverridesOut(
        style=parsed.style, unknown_kanji_target=unknown_kanji_target, jlpt_mix=jlpt_mix
    )


def validate_topic_slug(topic_slug: str, valid_slugs: set[str]) -> None:
    """Raise `GenerationError` (502) when the model named an unknown topic,
    or the `"surprise"` sentinel it was explicitly told never to use --
    `valid_slugs` is the live set of topic slugs, so "surprise" (never a
    real row) is rejected by the exact same check, no special case needed."""
    if topic_slug not in valid_slugs:
        raise GenerationError("The suggestion named an unknown topic.")


# --- the OpenAI call ----------------------------------------------------------


async def _post_chat_completion(api_base: str, api_key: str, payload: dict) -> dict:
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise GenerationError(
            f"The OpenAI API returned HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise GenerationError(f"Could not reach the OpenAI API: {exc}") from exc


def _parse_completion(body: dict) -> tuple[SuggestionSchema, dict]:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GenerationError("The OpenAI API returned no choices.") from exc

    if message.get("refusal"):
        raise GenerationError(f"The model refused: {message['refusal']}")

    content = message.get("content")
    if not content:
        raise GenerationError("The OpenAI API returned an empty response.")

    try:
        parsed = SuggestionSchema.model_validate_json(content)
    except (ValidationError, json.JSONDecodeError) as exc:
        logger.error("Suggestion model returned unusable JSON: %s", content[:500])
        raise GenerationError("The model returned an unexpected response.") from exc

    return parsed, (body.get("usage") or {})


@dataclass
class SuggestionResult:
    topic_slug: str
    length: Literal["short", "medium", "long"]
    preset: Literal["easy", "stretch", "challenge"]
    overrides: SuggestionOverridesOut | None
    reason: str
    usage: CallUsage
    model: str


async def generate_suggestion(
    *, config: RuntimeConfig, context: SuggestionContext, valid_topic_slugs: set[str]
) -> SuggestionResult:
    """Build the prompt, call the model, validate/clamp its answer.

    Raises `GenerationError` (409 with no key configured, 502 for any
    upstream failure, an unusable response, or an unknown/`"surprise"`
    topic).
    """
    if not config.openai_api_key:
        raise GenerationError("No OpenAI API key is configured.", status=409)

    system_prompt = build_suggestion_prompt(context)
    payload = {
        "model": config.help_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Suggest the next text now, following the instructions above."},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "suggestion",
                "strict": True,
                "schema": _strict_schema(SuggestionSchema),
            },
        },
    }

    body = await _post_chat_completion(config.openai_api_base, config.openai_api_key, payload)
    parsed, usage = _parse_completion(body)

    validate_topic_slug(parsed.topic_slug, valid_topic_slugs)

    return SuggestionResult(
        topic_slug=parsed.topic_slug,
        length=parsed.length,
        preset=parsed.preset,
        overrides=resolve_overrides(parsed.overrides),
        reason=parsed.reason.strip(),
        usage=usage_from_response(usage),
        model=config.help_model,
    )
