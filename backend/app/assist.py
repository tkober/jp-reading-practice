"""The LLM call behind the word popover's three helps (issue #10): Explain
word, Translate sentence, Explain grammar.

A plain chat completion, no Structured Outputs -- unlike `generation.py`'s
forced JSON schema, there is no shape to enforce beyond "short English
text", and the prompt's own word limits (`help_prompts.py`) do that work.
Reuses `generation.GenerationError`'s own status convention (409 no key,
502 for anything upstream) since the failure modes are identical, and the
same `httpx` + `RuntimeConfig` + `pricing.py` shape as that module's own
OpenAI call.
"""

from __future__ import annotations

import httpx

from .generation import GenerationError
from .pricing import CallUsage, usage_from_response
from .runtime_config import RuntimeConfig

#: The brief asks for at least 60s; a help answer is one short call, so
#: there is no reason to cut it any tighter than that.
TIMEOUT = 60.0


async def _post_chat_completion(api_base: str, api_key: str, model: str, prompt: str) -> dict:
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Answer now."},
        ],
    }
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


def _parse_completion(body: dict) -> tuple[str, dict]:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GenerationError("The OpenAI API returned no choices.") from exc

    if message.get("refusal"):
        raise GenerationError(f"The model refused: {message['refusal']}")

    content = message.get("content")
    if not content:
        raise GenerationError("The OpenAI API returned an empty response.")

    return content.strip(), (body.get("usage") or {})


async def generate_help_answer(*, config: RuntimeConfig, prompt: str) -> tuple[str, CallUsage]:
    """One plain chat completion against `RuntimeConfig.help_model`.

    Raises `GenerationError` (409 with no key configured, 502 for any
    upstream failure, a refusal, or an empty response).
    """
    if not config.openai_api_key:
        raise GenerationError("No OpenAI API key is configured.", status=409)

    body = await _post_chat_completion(
        config.openai_api_base, config.openai_api_key, config.help_model, prompt
    )
    answer, usage = _parse_completion(body)
    return answer, usage_from_response(usage)
