"""Cost calculation for the chat-completions models in `model_catalog.py`.

Same shape as jp-conversation-practice's `pricing.py`: a hand-maintained
USD-per-1M-token rate table, because there is no pricing API to ask instead
(see that module's own comment, and `model_catalog.py`'s "No pricing here
yet"). `rates_for()` returns `None` for a model this table does not know,
rather than falling back to a default rate the way jp-conversation-
practice's realtime pricing does -- that app always bills *some* realtime
model, so a fallback rate is better than nothing; this app's `cost_usd` is
nullable precisely so an unknown model can say "unknown" instead of quietly
reporting a wrong number (see the brief for issue #8).

**Where these numbers come from.** The brief for this table was to take the
rates from jp-conversation-practice's own `pricing.py` for whichever models
overlap, and leave every other model out rather than inventing a figure.
As of this writing that table only prices the *realtime* models
(`gpt-realtime*`) -- none of the curated chat models in this app's
`model_catalog.py` slots (`gpt-4o-mini`, `gpt-4o`, `gpt-5-mini`, `gpt-5`)
appear there. So this table starts empty: every text generated with a
curated model reports `cost_usd: null` until real numbers are added here by
hand, from a trusted source (OpenAI's published pricing page), the same way
`MODEL_RATES` elsewhere in the suite is kept in sync by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOKENS_PER_UNIT = 1_000_000


@dataclass(frozen=True)
class ChatModelRates:
    """USD price per 1M tokens for a chat-completions model."""

    input: float
    cached_input: float
    output: float


#: Deliberately empty -- see the module docstring. Add an entry here only
#: with a number traceable to a real source; do not estimate.
MODEL_RATES: dict[str, ChatModelRates] = {}


def rates_for(model: str) -> ChatModelRates | None:
    """The price table for `model`, or `None` if this table does not know it."""
    return MODEL_RATES.get(model)


def _as_int(value: Any) -> int:
    """Coerce a usage field to int, tolerating nulls and floats."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


@dataclass(frozen=True)
class CallUsage:
    """Token usage for one chat-completions call, as reported in its
    response's `usage` object."""

    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
        }


def usage_from_response(usage: dict[str, Any]) -> CallUsage:
    """Extract a `CallUsage` from a Chat Completions response's `usage`
    object. Cached tokens are reported *inside* `prompt_tokens_details`, as
    a subset of `prompt_tokens`."""
    details = usage.get("prompt_tokens_details") or {}
    return CallUsage(
        prompt_tokens=_as_int(usage.get("prompt_tokens")),
        completion_tokens=_as_int(usage.get("completion_tokens")),
        cached_tokens=_as_int(details.get("cached_tokens")),
    )


def cost_usd(model: str, calls: list[CallUsage]) -> float | None:
    """Total USD cost across every call this generation made, or `None` if
    `model` is not in `MODEL_RATES`."""
    rates = rates_for(model)
    if rates is None:
        return None

    total = 0.0
    for call in calls:
        uncached = max(call.prompt_tokens - call.cached_tokens, 0)
        total += (
            uncached * rates.input
            + call.cached_tokens * rates.cached_input
            + call.completion_tokens * rates.output
        )
    return total / TOKENS_PER_UNIT
