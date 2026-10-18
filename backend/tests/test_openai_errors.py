"""`app.openai_errors` (readable OpenAI error messages): every status/code
case the brief names, real-looking OpenAI error bodies, plus the "never the
raw body" guarantee (a monkeypatched `logger.warning` catches what actually
went to the log instead -- see `test_raw_body_is_logged_but_never_in_the_
returned_message`'s own comment for why not `caplog`)."""

from __future__ import annotations

import json

import httpx
import pytest

from app import openai_errors
from app.openai_errors import describe_connection_error, describe_http_status_error, describe_openai_error


def _status_error(status_code: int, body: dict | str) -> httpx.HTTPStatusError:
    text = body if isinstance(body, str) else json.dumps(body)
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, text=text)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("status_code must be an error status")


def test_401_invalid_key() -> None:
    exc = _status_error(
        401,
        {
            "error": {
                "message": "Incorrect API key provided: sk-***XYZ.",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        },
    )
    message = describe_http_status_error(exc, context="test")
    assert message == "The OpenAI API key was rejected — check it in Settings."
    assert "sk-***XYZ" not in message


def test_429_insufficient_quota() -> None:
    exc = _status_error(
        429,
        {
            "error": {
                "message": "You exceeded your current quota, please check your plan and "
                "billing details.",
                "type": "insufficient_quota",
                "code": "insufficient_quota",
            }
        },
    )
    message = describe_http_status_error(exc, context="test")
    assert message == (
        "OpenAI's rate limit or quota was reached — try again later or check your billing."
    )


def test_429_plain_rate_limit() -> None:
    exc = _status_error(
        429,
        {
            "error": {
                "message": "Rate limit reached for requests",
                "type": "requests",
                "code": "rate_limit_exceeded",
            }
        },
    )
    message = describe_http_status_error(exc, context="test")
    assert "rate limit or quota" in message


def test_5xx_is_a_transient_problem() -> None:
    exc = _status_error(500, {"error": {"message": "simulated outage"}})
    message = describe_http_status_error(exc, context="test")
    assert message == "OpenAI is having problems right now — try again in a moment."
    assert "simulated outage" not in message


def test_503_is_also_a_transient_problem() -> None:
    exc = _status_error(503, {"error": {"message": "The server had an error processing it."}})
    message = describe_http_status_error(exc, context="test")
    assert message == "OpenAI is having problems right now — try again in a moment."


def test_model_not_found_names_the_configured_model() -> None:
    exc = _status_error(
        404,
        {
            "error": {
                "message": "The model `gpt-99-turbo` does not exist or you do not have "
                "access to it.",
                "type": "invalid_request_error",
                "param": "model",
                "code": "model_not_found",
            }
        },
    )
    message = describe_http_status_error(exc, context="test", model="gpt-99-turbo")
    assert message == (
        "The model gpt-99-turbo is not available for this API key — pick another in Settings."
    )


def test_model_not_found_falls_back_to_the_message_when_no_model_is_passed() -> None:
    exc = _status_error(
        404,
        {
            "error": {
                "message": "The model `gpt-99-turbo` does not exist or you do not have "
                "access to it.",
                "code": "model_not_found",
            }
        },
    )
    message = describe_http_status_error(exc, context="test")
    assert "gpt-99-turbo" in message
    assert message.startswith("The model ")


def test_unmapped_error_keeps_the_upstream_message() -> None:
    exc = _status_error(
        400,
        {"error": {"message": "Invalid value for 'temperature': must be between 0 and 2."}},
    )
    message = describe_http_status_error(exc, context="test")
    assert message == (
        "OpenAI returned an error: Invalid value for 'temperature': must be between 0 and 2."
    )


def test_unparseable_body_falls_back_to_a_bare_status_line() -> None:
    exc = _status_error(400, "<html>not json</html>")
    message = describe_http_status_error(exc, context="test")
    assert message == "OpenAI returned HTTP 400."
    assert "<html>" not in message


def test_raw_body_is_logged_but_never_in_the_returned_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not `caplog`: alembic's own `env.py` calls `logging.config.fileConfig`
    # (default `disable_existing_loggers=True`) once per test session, via
    # the DB fixture's migration run -- which disables every `app.*` logger
    # already created at collection time, `caplog`'s own handler included.
    # Patching the module's `logger.warning` directly sidesteps that.
    logged: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        openai_errors.logger, "warning", lambda *args: logged.append(args)
    )
    exc = _status_error(500, {"error": {"message": "simulated outage", "trace": "x" * 50}})

    message = describe_http_status_error(exc, context="text generation")

    assert "simulated outage" not in message
    assert len(logged) == 1
    logged_text = " ".join(str(part) for part in logged[0])
    assert "simulated outage" in logged_text
    assert "text generation" in logged_text


def test_connection_error_is_readable() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    exc = httpx.ConnectError("Connection refused", request=request)
    message = describe_connection_error(exc, context="test")
    assert message == "Could not reach OpenAI — check your connection and try again."


def test_timeout_is_its_own_message() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    exc = httpx.ReadTimeout("timed out", request=request)
    message = describe_connection_error(exc, context="test")
    assert message == "OpenAI did not respond in time — try again in a moment."


def test_describe_openai_error_dispatches_by_exception_type() -> None:
    status_exc = _status_error(500, {"error": {"message": "simulated outage"}})
    assert describe_openai_error(status_exc, context="test") == describe_http_status_error(
        status_exc, context="test"
    )

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    timeout_exc = httpx.ReadTimeout("timed out", request=request)
    assert describe_openai_error(timeout_exc, context="test") == describe_connection_error(
        timeout_exc, context="test"
    )
