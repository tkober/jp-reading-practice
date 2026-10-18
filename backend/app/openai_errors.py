"""One shared place to turn an OpenAI HTTP failure into a short, plain
English sentence a learner can act on.

Every OpenAI call in this app used to format `exc.response.text[:500]`
straight into the message it raised (`generation.py`, `assist.py`,
`suggestions.py`) or returned (`news.py`'s web-search material path) --
the raw upstream body, a JSON blob, reaching the learner verbatim through
the frontend's own "The server refused: ..." prefix
(`frontend/src/app/core/api.ts`'s `rethrow()`). This module is the one
place that decides what to say instead; the raw body is only ever logged
(`logger.warning`), never returned to a caller.

`describe_openai_error()` is the one entry point every call site's own
`except httpx.HTTPStatusError`/`except httpx.HTTPError` pair should go
through, replacing each one's own ad-hoc f-string.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

#: How much of the raw body is worth keeping in the log -- plenty to
#: diagnose a real problem, not so much that a pathological body floods it.
_LOGGED_BODY_CHARS = 2000

_BACKTICKED = re.compile(r"`([^`]+)`")


def _parse_error_body(body_text: str) -> tuple[str | None, str | None, str | None]:
    """`(message, code, type)` from an OpenAI-shaped `{"error": {...}}`
    body -- every field `None` when the body is not JSON, not an object, or
    has no `error` object (a proxy/gateway error page, for instance)."""
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, TypeError):
        return None, None, None
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None, None, None
    message = error.get("message")
    code = error.get("code")
    error_type = error.get("type")
    return (
        message if isinstance(message, str) and message.strip() else None,
        code if isinstance(code, str) else None,
        error_type if isinstance(error_type, str) else None,
    )


def _model_from_message(message: str | None) -> str | None:
    """OpenAI's own "model not found" message names the model inside
    backticks (e.g. "The model `gpt-99` does not exist..."); used only as a
    fallback when the call site did not pass its own `model`."""
    if not message:
        return None
    found = _BACKTICKED.search(message)
    return found.group(1) if found else None


def describe_http_status_error(
    exc: httpx.HTTPStatusError, *, context: str, model: str | None = None
) -> str:
    """One short English sentence for an OpenAI HTTP error *response* --
    parses the JSON body's `error.message`/`error.code`/`error.type` when
    present and maps the common cases to plain words:

    - 401 (or `code == "invalid_api_key"`): the configured key is wrong.
    - 429, or `code`/`type` naming a rate limit or quota problem: try again
      later, or check billing.
    - 5xx: a transient upstream problem, try again in a moment.
    - `code == "model_not_found"`: the configured model is not available to
      this key (`model` is the model the call was actually made with --
      preferred over trying to pick the name back out of the upstream's own
      message).

    Anything else falls back to the upstream's own `error.message` (never
    the raw body) prefixed with "OpenAI returned an error:", or, lacking
    even that, a bare status line. `context` (e.g. "text generation",
    "assist", "suggestion", "web search material") only names the call site
    in the server log, never in the returned sentence.
    """
    status = exc.response.status_code
    body_text = exc.response.text
    logger.warning(
        "OpenAI API error during %s: HTTP %s: %s", context, status, body_text[:_LOGGED_BODY_CHARS]
    )

    message, code, error_type = _parse_error_body(body_text)

    if status == 401 or code == "invalid_api_key":
        return "The OpenAI API key was rejected — check it in Settings."
    if (
        status == 429
        or code in ("insufficient_quota", "rate_limit_exceeded")
        or error_type == "insufficient_quota"
    ):
        return (
            "OpenAI's rate limit or quota was reached — try again later or check your billing."
        )
    if status >= 500:
        return "OpenAI is having problems right now — try again in a moment."
    if code == "model_not_found":
        name = model or _model_from_message(message) or "The configured model"
        return f"The model {name} is not available for this API key — pick another in Settings."
    if message:
        return f"OpenAI returned an error: {message}"
    return f"OpenAI returned HTTP {status}."


def describe_connection_error(exc: httpx.HTTPError, *, context: str) -> str:
    """One short English sentence for a failure that never got an HTTP
    response at all -- a timeout or a connection error. `context` is log-
    only, same as `describe_http_status_error`."""
    logger.warning("Could not reach the OpenAI API during %s: %r", context, exc)
    if isinstance(exc, httpx.TimeoutException):
        return "OpenAI did not respond in time — try again in a moment."
    return "Could not reach OpenAI — check your connection and try again."


def describe_openai_error(exc: httpx.HTTPError, *, context: str, model: str | None = None) -> str:
    """Dispatch to `describe_http_status_error`/`describe_connection_error`
    depending on whether `exc` carries an upstream response at all -- the
    one function every call site's `except httpx.HTTPStatusError`/
    `except httpx.HTTPError` pair needs."""
    if isinstance(exc, httpx.HTTPStatusError):
        return describe_http_status_error(exc, context=context, model=model)
    return describe_connection_error(exc, context=context)
