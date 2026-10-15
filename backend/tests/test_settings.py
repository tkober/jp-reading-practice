"""Settings API: overrides, fallbacks and secret handling."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import get_settings


async def read(client: AsyncClient) -> dict:
    return (await client.get("/api/settings")).json()


async def patch(client: AsyncClient, **fields: object) -> dict:
    return (await client.put("/api/settings", json=fields)).json()


async def test_defaults_come_from_the_environment(client: AsyncClient) -> None:
    body = await read(client)
    env = get_settings()

    assert body["generation_model"] == env.generation_model
    assert body["help_model"] == env.help_model
    assert body["kanji_trainer_mcp_url"] == env.kanji_trainer_mcp_url
    assert body["web_search_enabled"] == env.web_search_enabled
    assert body["openai_api_key_set"] is False


async def test_patch_overrides_only_the_given_fields(client: AsyncClient) -> None:
    before = await read(client)

    body = await patch(client, generation_model="gpt-5-mini")

    assert body["generation_model"] == "gpt-5-mini"
    assert body["help_model"] == before["help_model"]
    assert body["kanji_trainer_mcp_url"] == before["kanji_trainer_mcp_url"]


async def test_clearing_an_override_falls_back_to_the_environment(client: AsyncClient) -> None:
    await patch(client, help_model="gpt-5")
    assert (await read(client))["help_model"] == "gpt-5"

    await patch(client, help_model="")

    assert (await read(client))["help_model"] == get_settings().help_model


async def test_api_key_is_never_returned_in_full(client: AsyncClient) -> None:
    secret = "sk-proj-abcdefghijklmnop1234"
    await patch(client, openai_api_key=secret)

    response = await client.get("/api/settings")
    body = response.json()

    assert body["openai_api_key_set"] is True
    assert body["openai_api_key_hint"] == "…1234"
    assert body["openai_api_key_from_env"] is False
    assert secret not in response.text


async def test_key_source_is_reported_so_the_ui_can_explain_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key-0000")
    get_settings.cache_clear()
    try:
        body = await read(client)

        assert body["openai_api_key_set"] is True
        assert body["openai_api_key_from_env"] is True
    finally:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        get_settings.cache_clear()


async def test_invalid_model_id_is_rejected(client: AsyncClient) -> None:
    before = await read(client)

    body = await patch(client, generation_model="../../etc/passwd")

    assert body["generation_model"] == before["generation_model"]


async def test_an_unlisted_but_well_formed_model_is_accepted(client: AsyncClient) -> None:
    # The point of the free-text option: a model released after this deploy.
    body = await patch(client, help_model="gpt-realtime-9-preview")

    assert body["help_model"] == "gpt-realtime-9-preview"


async def test_web_search_enabled_can_be_toggled_and_cleared(client: AsyncClient) -> None:
    assert (await read(client))["web_search_enabled"] is False

    body = await patch(client, web_search_enabled=True)
    assert body["web_search_enabled"] is True

    body = await patch(client, web_search_enabled=None)
    assert body["web_search_enabled"] is False


async def test_models_endpoint_lists_both_slots(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import model_catalog
    from app.api import settings as settings_api

    async def fake_fetch(api_base: str, api_key: str) -> dict[str, str | None]:
        return {"gpt-5-mini": None}

    monkeypatch.setattr(model_catalog, "_fetch_models", fake_fetch)
    monkeypatch.setattr(settings_api, "_catalog", model_catalog.ModelCatalog())

    await patch(client, openai_api_key="sk-test-key-for-catalog")
    body = (await client.get("/api/settings/models")).json()

    assert [slot["key"] for slot in body["slots"]] == list(model_catalog.SLOTS_BY_KEY)
    assert body["live_ok"] is True
    generation = body["slots"][0]
    assert "gpt-5-mini" in [option["id"] for option in generation["options"]]
