"""Text generation (issue #8): one OpenAI call, measured against the
learner's level, with at most one correction round.

Mirrors jp-conversation-practice's `analysis.py`: Chat Completions with
Structured Outputs (`_strict_schema`), the same way, against the OpenAI key
and model from `RuntimeConfig`. The one real difference is that this module
also measures its own output (via `app.analysis.analyze()`, using the live
Kanji Trainer known set and JLPT levels) and, when the result misses the
target badly enough, sends back exactly what was off for one revision --
see `decide_correction()` and `build_correction_instructions()`
(`prompts.py`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field, ValidationError

from . import kanji_trainer as kt
from . import news
from .analysis import analyze, collect_lemmas
from .known_set import KnownSet, fetch_known_set
from .models import JlptMixTarget, Metrics, QuestionOut, TextAnalysis
from .openai_errors import describe_openai_error
from .pricing import CallUsage, usage_from_response, web_search_cost_usd
from .prompts import MaterialItem, build_correction_instructions, build_generation_instructions
from .runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

#: A correction round triggers when EITHER condition fires: the unknown-kanji
#: share is both 1.5x the target and at least 2 points above it (so a tiny
#: target, e.g. 2%, does not trigger on rounding noise alone), or the length
#: is off by more than 25%. See the brief for issue #8.
_UNKNOWN_KANJI_RATIO_TRIGGER = 1.5
_UNKNOWN_KANJI_ABSOLUTE_MARGIN = 0.02
_LENGTH_RATIO_TRIGGER = 0.25

#: At most one correction call, ever.
MAX_ATTEMPTS = 2


class GenerationError(RuntimeError):
    """Something about the generation call itself failed.

    `status` is the HTTP status `api/texts.py` answers with: 409 when no key
    is configured, 502 for everything that is the upstream's fault (a bad
    response, a timeout, a refusal, or output that does not validate).
    """

    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


# --- the model's own structured output --------------------------------------


class GeneratedQuestion(BaseModel):
    question: str = ""
    options: list[str] = Field(default_factory=list)
    answer_index: int = -1


class GeneratedTextSchema(BaseModel):
    """The shape `generate_text()` forces the model into, via Structured
    Outputs -- title, paragraphs (plain strings, one per paragraph) and 2-3
    comprehension questions."""

    title: str = ""
    paragraphs: list[str] = Field(default_factory=list)
    questions: list[GeneratedQuestion] = Field(default_factory=list)
    #: Which `# Material` item (its 0-based position in the prompt's own
    #: list) the text retold -- only meaningful when material was given at
    #: all; `-1` otherwise. Structured Outputs' strict mode still forces
    #: the model to return *something* here even for a topic with no
    #: material (there is no per-field "optional" in strict mode), so a
    #: non-news-backed topic's generations simply carry a meaningless `-1`
    #: that `generate_text()` below never reads.
    source_index: int = -1


def _strict_schema(model: type[BaseModel]) -> dict:
    """Turn a Pydantic JSON schema into an OpenAI ``strict``-compatible one
    -- every object needs all its properties in `required` plus
    `additionalProperties: false`. Identical to jp-conversation-practice's
    `analysis._strict_schema`."""

    def tighten(node: object) -> object:
        if isinstance(node, list):
            return [tighten(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {key: tighten(value) for key, value in node.items()}
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
        return node

    return tighten(model.model_json_schema())


# --- validation ---------------------------------------------------------------


def validate_questions(questions: list[GeneratedQuestion]) -> list[GeneratedQuestion]:
    """Keep only the well-formed questions: exactly 4 non-empty options, no
    duplicate options, and `answer_index` in range. Order is preserved, and
    `answer_index` is kept (issue #9 checks answers server-side against the
    stored row) -- `to_question_out` is the one that strips it for the API
    response.
    """
    valid: list[GeneratedQuestion] = []
    for question in questions:
        options = [option.strip() for option in question.options]
        if not question.question.strip():
            continue
        if len(options) != 4 or any(not option for option in options):
            continue
        if len(set(options)) != len(options):
            continue
        if not (0 <= question.answer_index < len(options)):
            continue
        valid.append(
            GeneratedQuestion(
                question=question.question.strip(),
                options=options,
                answer_index=question.answer_index,
            )
        )
    return valid


def to_question_out(questions: list[GeneratedQuestion]) -> list[QuestionOut]:
    """Strip `answer_index` for the API response -- never sent to the
    browser (brief for issue #8)."""
    return [QuestionOut(question=q.question, options=list(q.options)) for q in questions]


# --- correction decision ------------------------------------------------------


def extract_offending_words(text_analysis: TextAnalysis) -> list[str]:
    """Words whose surface uses at least one unknown kanji, as
    "surface (kanji)" strings, deduplicated in first-seen order -- what the
    correction prompt names as "the concrete offending words"."""
    seen: dict[str, None] = {}
    for paragraph in text_analysis.paragraphs:
        for token in paragraph.tokens:
            unknown = [info.character for info in token.kanji if not info.known]
            if not unknown:
                continue
            label = f"{token.surface} ({''.join(unknown)})"
            seen.setdefault(label, None)
    return list(seen)


def decide_correction(
    metrics: Metrics, *, unknown_kanji_target: float, target_length_chars: int
) -> bool:
    """Whether the one allowed correction round should run -- see the brief
    for issue #8: the unknown-kanji share is both 1.5x the target and at
    least `_UNKNOWN_KANJI_ABSOLUTE_MARGIN` above it, or the length is off by
    more than `_LENGTH_RATIO_TRIGGER`."""
    measured_share = metrics.unknown_kanji_share
    triggers_kanji = (
        unknown_kanji_target > 0
        and measured_share > unknown_kanji_target * _UNKNOWN_KANJI_RATIO_TRIGGER
        and measured_share > unknown_kanji_target + _UNKNOWN_KANJI_ABSOLUTE_MARGIN
    )
    length_ratio_error = (
        abs(metrics.characters - target_length_chars) / target_length_chars
        if target_length_chars
        else 0.0
    )
    triggers_length = length_ratio_error > _LENGTH_RATIO_TRIGGER
    return triggers_kanji or triggers_length


def _badness(metrics: Metrics, *, unknown_kanji_target: float, target_length_chars: int) -> float:
    """How far an attempt is from the targets -- lower is closer. Used only
    to pick between two attempts ("keep whichever attempt is closer to
    target"), never to decide whether a correction round runs at all."""
    share_excess = max(0.0, metrics.unknown_kanji_share - unknown_kanji_target)
    length_relative_error = (
        abs(metrics.characters - target_length_chars) / target_length_chars
        if target_length_chars
        else 0.0
    )
    return share_excess + length_relative_error


# --- the OpenAI call -----------------------------------------------------------


async def _post_chat_completion(api_base: str, api_key: str, payload: dict) -> dict:
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise GenerationError(
            describe_openai_error(exc, context="text generation", model=payload.get("model"))
        ) from exc
    except httpx.HTTPError as exc:
        raise GenerationError(describe_openai_error(exc, context="text generation")) from exc


def _parse_completion(body: dict) -> tuple[GeneratedTextSchema, dict]:
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
        parsed = GeneratedTextSchema.model_validate_json(content)
    except (ValidationError, json.JSONDecodeError) as exc:
        logger.error("Generation model returned unusable JSON: %s", content[:500])
        raise GenerationError("The model returned an unexpected response.") from exc

    return parsed, (body.get("usage") or {})


def join_paragraphs(paragraphs: list[str]) -> str:
    """Paragraphs separated by one blank line, per the stored `body`'s
    format (brief, `texts.body`)."""
    return "\n\n".join(paragraph.strip() for paragraph in paragraphs if paragraph.strip())


# --- orchestration -------------------------------------------------------------


@dataclass
class GenerationOutcome:
    title: str
    body: str
    questions: list[GeneratedQuestion]
    text_analysis: TextAnalysis
    attempts: int
    calls: list[CallUsage]
    model: str
    kanji_trainer_error: str | None
    known_snapshot: dict[str, object]
    #: `{title, link, published, via}` for the one material item the text
    #: retold (issue #15), or `None` when there was no material at all --
    #: never set together with `material_error`.
    source: dict[str, object] | None = None
    #: Why no material was available for a news-backed topic (a dead feed,
    #: nothing fresh, a web-search failure) -- reported the same way
    #: `kanji_trainer_error` is: generation still happens, just with the
    #: frame's own neutral fallback line instead of real material. `None`
    #: for a topic with no `feed_urls` at all, and for one whose material
    #: fetch succeeded.
    material_error: str | None = None
    #: The `web_search` tool's own flat per-call fee (issue #15,
    #: `pricing.web_search_cost_usd`) -- *not* included in `calls` (which
    #: only ever carries token usage); `api/texts.py` adds this on top of
    #: `pricing.cost_usd(model, calls)` for the stored `cost_usd`.
    extra_cost_usd: float = 0.0


async def _gather_material(
    *, config: RuntimeConfig, feed_urls: list[str], topic_title: str
) -> tuple[list[news.NewsItem], str | None, CallUsage | None]:
    """The material step (issue #15): nothing at all for a topic with no
    `feed_urls` (not news-backed); otherwise RSS by default, or one OpenAI
    web-search call instead when `RuntimeConfig.web_search_enabled` is on.

    Returns `(items, material_error, extra_usage)` -- `extra_usage` is only
    ever set by the web-search path (its own token cost), and `items`/
    `material_error` are mutually exclusive, same as `news.MaterialResult`.
    """
    if not feed_urls:
        return [], None, None

    if config.web_search_enabled:
        try:
            result, usage = await news.fetch_web_search_material(config, topic_title)
        except news.WebSearchUnsupported as exc:
            return [], str(exc), None
        return result.items, result.error, usage

    result = await news.fetch_rss_material(feed_urls)
    return result.items, result.error, None


async def _known_snapshot_and_set(url: str) -> tuple[KnownSet, dict[str, object], str | None]:
    """The known set plus the small "counts + level" snapshot stored on the
    row -- never the full kanji/vocabulary lists (brief: `known_snapshot`).
    Degrades to an empty known set (every kanji looks unknown, generation
    falls back to the JLPT mix alone) exactly like `/api/analysis` does.
    """
    error: str | None = None
    try:
        known = await fetch_known_set(url)
    except kt.KanjiTrainerUnavailable as exc:
        known = KnownSet()
        error = str(exc)

    level: int | None = None
    if error is None:
        try:
            summary = await kt.get_learning_summary(url)
            level = summary.current_level
        except kt.KanjiTrainerUnavailable as exc:
            # The known lists above may still have come through fine; only
            # the level is missing, so this does not overwrite `error`.
            logger.warning("Could not fetch Kanji Trainer level for known_snapshot: %s", exc)

    snapshot = {
        "level": level,
        "known_kanji_count": len(known.kanji),
        "known_vocabulary_count": len(known.vocabulary),
        "kanji_trainer_error": error,
    }
    return known, snapshot, error


async def _jlpt_lookup_for(url: str, text: str, kanji_trainer_error: str | None) -> dict:
    if kanji_trainer_error is not None:
        return {}
    lemma_keys = collect_lemmas(text)
    if not lemma_keys:
        return {}
    try:
        results = await kt.get_jlpt_levels(
            url, [kt.JlptQuery(text=lemma, reading=reading) for lemma, reading in lemma_keys]
        )
    except kt.KanjiTrainerUnavailable as exc:
        logger.warning("Could not fetch JLPT levels for generated text: %s", exc)
        return {}
    return dict(zip(lemma_keys, results, strict=True))


async def generate_text(
    *,
    config: RuntimeConfig,
    kanji_trainer_url: str,
    topic_prompt: str,
    style: str,
    length_chars: int,
    jlpt_mix: JlptMixTarget,
    unknown_kanji_target: float,
    topic_title: str = "",
    feed_urls: list[str] | None = None,
) -> GenerationOutcome:
    """Generate one text, measure it, and run at most one correction round.

    `topic_title`/`feed_urls` (issue #15) drive the material step --
    `feed_urls` empty (the default) means this topic is not news-backed and
    behaves exactly as before this issue: no material step at all, no
    `# Material` section, no `source`/`material_error`.

    Raises `GenerationError` (status 409 with no key configured, 502 for any
    upstream failure or unusable output).
    """
    if not config.openai_api_key:
        raise GenerationError("No OpenAI API key is configured.", status=409)

    known, known_snapshot, kanji_trainer_error = await _known_snapshot_and_set(kanji_trainer_url)
    known_kanji_str = "".join(sorted(known.kanji)) if kanji_trainer_error is None else None

    material_items, material_error, material_usage = await _gather_material(
        config=config, feed_urls=feed_urls or [], topic_title=topic_title
    )
    material = (
        [
            MaterialItem(
                title=item.title,
                summary=item.summary,
                published=item.published.isoformat() if item.published else "",
            )
            for item in material_items
        ]
        if material_items
        else None
    )

    system_prompt = build_generation_instructions(
        topic_prompt=topic_prompt,
        style=style,
        length_chars=length_chars,
        jlpt_mix=jlpt_mix,
        unknown_kanji_target=unknown_kanji_target,
        known_kanji=known_kanji_str,
        kanji_trainer_error=kanji_trainer_error,
        material=material,
        material_error=material_error,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Write the text now, following the instructions above."},
    ]

    def payload() -> dict:
        return {
            "model": config.generation_model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "generated_text",
                    "strict": True,
                    "schema": _strict_schema(GeneratedTextSchema),
                },
            },
        }

    # The web-search material call's own token usage (issue #15) -- its
    # flat per-call fee is `extra_cost_usd`, computed separately below.
    calls: list[CallUsage] = [material_usage] if material_usage is not None else []

    async def one_attempt() -> tuple[GeneratedTextSchema, str, TextAnalysis]:
        body_response = await _post_chat_completion(
            config.openai_api_base, config.openai_api_key, payload()
        )
        parsed, usage = _parse_completion(body_response)
        calls.append(usage_from_response(usage))
        body_text = join_paragraphs(parsed.paragraphs)
        jlpt_lookup = await _jlpt_lookup_for(kanji_trainer_url, body_text, kanji_trainer_error)
        analysis = analyze(body_text, known, jlpt_lookup)
        return parsed, body_text, analysis

    first_parsed, first_body, first_analysis = await one_attempt()
    # Record the assistant's own first answer so a correction round is a
    # genuine follow-up turn, not a repeat of the same request.
    messages.append({"role": "assistant", "content": first_parsed.model_dump_json()})

    needs_correction = decide_correction(
        first_analysis.metrics,
        unknown_kanji_target=unknown_kanji_target,
        target_length_chars=length_chars,
    )

    best_parsed, best_body, best_analysis, attempts = first_parsed, first_body, first_analysis, 1

    if needs_correction:
        offending = extract_offending_words(first_analysis)
        messages.append(
            {
                "role": "user",
                "content": build_correction_instructions(
                    body=first_body,
                    offending_words=offending,
                    measured_unknown_kanji_share=first_analysis.metrics.unknown_kanji_share,
                    unknown_kanji_target=unknown_kanji_target,
                    measured_length_chars=first_analysis.metrics.characters,
                    target_length_chars=length_chars,
                ),
            }
        )
        second_parsed, second_body, second_analysis = await one_attempt()
        attempts = 2

        first_score = _badness(
            first_analysis.metrics,
            unknown_kanji_target=unknown_kanji_target,
            target_length_chars=length_chars,
        )
        second_score = _badness(
            second_analysis.metrics,
            unknown_kanji_target=unknown_kanji_target,
            target_length_chars=length_chars,
        )
        if second_score < first_score:
            best_parsed, best_body, best_analysis = second_parsed, second_body, second_analysis

    valid_questions = validate_questions(best_parsed.questions)
    if len(valid_questions) < 2:
        raise GenerationError(
            "The model returned too few valid comprehension questions.", status=502
        )

    source: dict[str, object] | None = None
    if material_items:
        index = best_parsed.source_index
        if not (0 <= index < len(material_items)):
            # The model did not return a usable index for the material it
            # was given -- attribute the text to the first item rather than
            # losing the source link entirely (brief: the retelling is of
            # "one" item either way, and this is the one listed first).
            index = 0
        chosen = material_items[index]
        source = {
            "title": chosen.title,
            "link": chosen.link,
            "published": chosen.published.isoformat() if chosen.published else None,
            "via": "web_search" if config.web_search_enabled else "rss",
        }

    return GenerationOutcome(
        title=best_parsed.title.strip(),
        body=best_body,
        questions=valid_questions,
        text_analysis=best_analysis,
        attempts=attempts,
        calls=calls,
        model=config.generation_model,
        kanji_trainer_error=kanji_trainer_error,
        known_snapshot=known_snapshot,
        source=source,
        material_error=material_error,
        extra_cost_usd=web_search_cost_usd(1) if material_usage is not None else 0.0,
    )
