"""Chat-completions pricing (issue #8 review follow-up): a known model
computes an exact cost, an unknown one reports `None` rather than a guess."""

from __future__ import annotations

from app.pricing import CallUsage, cost_usd, rates_for


def test_known_model_gets_an_exact_cost() -> None:
    # gpt-4o-mini: $0.15 / $0.075 / $0.60 per 1M (input / cached input / output).
    calls = [CallUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, cached_tokens=0)]

    cost = cost_usd("gpt-4o-mini", calls)

    assert cost == 0.15 + 0.60


def test_cached_tokens_are_billed_at_the_cached_rate() -> None:
    calls = [
        CallUsage(prompt_tokens=1_000_000, completion_tokens=0, cached_tokens=1_000_000)
    ]

    cost = cost_usd("gpt-4o-mini", calls)

    assert cost == 0.075


def test_cost_sums_across_multiple_calls() -> None:
    calls = [
        CallUsage(prompt_tokens=1_000_000, completion_tokens=0, cached_tokens=0),
        CallUsage(prompt_tokens=1_000_000, completion_tokens=0, cached_tokens=0),
    ]

    cost = cost_usd("gpt-4o-mini", calls)

    assert cost == 0.15 * 2


def test_unknown_model_is_none() -> None:
    calls = [CallUsage(prompt_tokens=100, completion_tokens=50, cached_tokens=0)]

    assert cost_usd("some-future-model", calls) is None
    assert rates_for("some-future-model") is None


def test_every_curated_generation_model_has_a_rate() -> None:
    # gpt-4o-mini, gpt-4o, gpt-5-mini, gpt-5 -- the curated models in
    # model_catalog.py's "generation"/"help" slots.
    for model in ("gpt-4o-mini", "gpt-4o", "gpt-5-mini", "gpt-5"):
        assert rates_for(model) is not None, f"{model} should have a rate"
