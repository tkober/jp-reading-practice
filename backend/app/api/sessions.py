"""Reading session API (issue #9).

A session walks `reading -> questions -> finished`, driven entirely by this
router: `POST /api/sessions` starts one on a text (reading it again creates
a *new* session, never reuses an old one), `GET /api/sessions/{id}` is what
`/read/:sessionId` reloads to resume wherever it left off (active time
included), and everything else below moves it forward one step. `GET
/api/reading/pace` (`pace_router`, mounted at a different prefix -- see
`api/__init__.py`) is the one route here that is not about a specific
session at all, just the setup/gate screens' duration estimate.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import dictionary, stretch, stretch_store
from .. import kanji_trainer as kt
from ..assist import generate_chat_answer, generate_help_answer
from ..db import (
    ChatMessage,
    GeneratedText,
    HelpAnswer,
    HelpEvent,
    ReadingSession,
    StretchAdjustment,
    get_session,
)
from ..generation import GenerationError
from ..help_prompts import (
    build_explain_grammar_instructions,
    build_explain_grammar_part_instructions,
    build_explain_word_instructions,
    build_translate_part_instructions,
    build_translate_sentence_instructions,
    build_tutor_messages,
    focus_question,
    focus_question_part,
)
from ..helps import WEIGHTS, helps_per_100_words as _helps_per_100_words
from ..models import (
    AnswerRequest,
    AnswerResult,
    AssistRequest,
    AssistResult,
    ChatMessageOut,
    ChatRequest,
    ChatResult,
    FinishReadingRequest,
    HelpRequest,
    HelpResult,
    LookedUpWordOut,
    LookupRequest,
    ReadingPaceOut,
    SessionAnswerOut,
    SessionCreateRequest,
    SessionOut,
    SessionSummaryOut,
    SessionTimeOut,
    SessionTimeRequest,
    WordLookupOut,
)
from ..pricing import cost_usd
from ..runtime_config import load_runtime_config
from ..sentences import (
    Sentence,
    Span,
    find_sentence,
    parse_span_target,
    resolve_span,
    span_target,
    split_sentences,
)
from .texts import _text_out

router = APIRouter()
pace_router = APIRouter()

#: kanji-trainer's own WaniKani-style stage names (its `app/srs.py`'s
#: `STAGE_NAMES`), duplicated here in miniature -- there is no shared
#: package between the two repos, same situation `kanji_trainer.py`'s own
#: module doc comment describes for the rest of this client.
_SRS_STAGE_NAMES = (
    "Unlearned",
    "Apprentice I",
    "Apprentice II",
    "Apprentice III",
    "Apprentice IV",
    "Guru I",
    "Guru II",
    "Master",
    "Enlightened",
    "Burned",
)

#: `GET /api/reading/pace`'s fallback until enough history exists.
DEFAULT_CHARS_PER_MINUTE = 150
PACE_MIN_SESSIONS = 3
PACE_SAMPLE_SESSIONS = 5


async def _get_session_or_404(session: AsyncSession, session_id: int) -> ReadingSession:
    row = await session.get(ReadingSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return row


async def _get_text_or_404(session: AsyncSession, text_id: int) -> GeneratedText:
    row = await session.get(GeneratedText, text_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Text not found.")
    return row


def _require_status(row: ReadingSession, expected: str) -> None:
    if row.status != expected:
        raise HTTPException(
            status_code=409,
            detail=f"The session is not in the {expected!r} phase (it is {row.status!r}).",
        )


def _find_token(text_row: GeneratedText, token_id: str) -> dict | None:
    for paragraph in text_row.analysis["paragraphs"]:
        for token in paragraph["tokens"]:
            if token["id"] == token_id:
                return token
    return None


def _lemma_reading(token: dict) -> str:
    """`Token.lemma_reading`, falling back to the surface reading for texts
    stored before #9 added the field."""
    return token.get("lemma_reading") or token["reading"]


def _session_out(session_row: ReadingSession, text_row: GeneratedText) -> SessionOut:
    questions = text_row.questions
    answers_out = []
    for index, option_index in enumerate(session_row.answers):
        correct_index = None
        if option_index is not None and index < len(questions):
            correct_index = questions[index]["answer_index"]
        answers_out.append(
            SessionAnswerOut(option_index=option_index, correct_index=correct_index)
        )

    return SessionOut(
        id=session_row.id,
        text=_text_out(text_row),
        status=session_row.status,  # type: ignore[arg-type]
        started_at=session_row.started_at,
        active_ms=session_row.active_ms,
        paused_ms=session_row.paused_ms,
        answers=answers_out,
        comprehension_correct=session_row.comprehension_correct,
    )


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    payload: SessionCreateRequest, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    """Reading a text again is a new session, never a reused one -- see the
    module doc comment."""
    text_row = await _get_text_or_404(session, payload.text_id)
    row = ReadingSession(
        text_id=text_row.id,
        status="reading",
        answers=[None] * len(text_row.questions),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _session_out(row, text_row)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session_route(
    session_id: int, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    row = await _get_session_or_404(session, session_id)
    text_row = await _get_text_or_404(session, row.text_id)
    return _session_out(row, text_row)


@router.put("/{session_id}/time", response_model=SessionTimeOut)
async def heartbeat(
    session_id: int, payload: SessionTimeRequest, session: AsyncSession = Depends(get_session)
) -> SessionTimeOut:
    """Monotonic: a heartbeat only ever raises the stored totals, matching
    `finish-reading`'s own use of the same rule -- a reload that resends an
    older snapshot (e.g. a slow request that landed after a newer one) must
    never claw time back."""
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "reading")
    row.active_ms = max(row.active_ms, payload.active_ms)
    row.paused_ms = max(row.paused_ms, payload.paused_ms)
    await session.commit()
    return SessionTimeOut(active_ms=row.active_ms, paused_ms=row.paused_ms)


async def _log_help(
    session: AsyncSession,
    session_row: ReadingSession,
    *,
    kind: str,
    token_id: str,
    target: str,
    lemma: str,
    surface: str,
    cost_usd: float | None = None,
) -> HelpResult:
    """Insert one help event, deduped by `(session_id, kind, target)` -- a
    repeat is a no-op (`counted=False`), never an error. `target` is the
    lemma for a word-kind help, the sentence key for a sentence-kind one
    (see `db.HelpEvent`'s docstring and `sentences.py`)."""
    weight = WEIGHTS[kind]
    stmt = (
        postgresql_insert(HelpEvent)
        .values(
            session_id=session_row.id,
            kind=kind,
            target=target,
            token_id=token_id,
            lemma=lemma,
            surface=surface,
            weight=weight,
            at_ms=session_row.active_ms,
            cost_usd=cost_usd,
        )
        .on_conflict_do_nothing(index_elements=["session_id", "kind", "target"])
    )
    result = await session.execute(stmt)
    await session.commit()
    return HelpResult(counted=result.rowcount > 0, weight=weight)


@router.post("/{session_id}/helps", response_model=HelpResult)
async def log_help(
    session_id: int, payload: HelpRequest, session: AsyncSession = Depends(get_session)
) -> HelpResult:
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "reading")
    text_row = await _get_text_or_404(session, row.text_id)
    token = _find_token(text_row, payload.token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Unknown token.")
    return await _log_help(
        session,
        row,
        kind=payload.kind,
        token_id=payload.token_id,
        target=token["lemma"],
        lemma=token["lemma"],
        surface=token["surface"],
    )


async def _known_status(url: str, lemma: str) -> str:
    """"Kanji Trainer: Guru II" / "Not in Kanji Trainer" / "Kanji Trainer
    unavailable" -- never raises, per the brief ("never fail the lookup
    because of it")."""
    try:
        results = await kt.lookup_items(url, [lemma])
    except kt.KanjiTrainerUnavailable:
        return "Kanji Trainer unavailable"

    result = results[0] if results else None
    if result is None or not result.found or not result.matches:
        return "Not in Kanji Trainer"

    stage = max(0, min(len(_SRS_STAGE_NAMES) - 1, result.matches[0].srs_stage))
    return f"Kanji Trainer: {_SRS_STAGE_NAMES[stage]}"


@router.post("/{session_id}/lookups", response_model=WordLookupOut)
async def log_lookup(
    session_id: int, payload: LookupRequest, session: AsyncSession = Depends(get_session)
) -> WordLookupOut:
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "reading")
    text_row = await _get_text_or_404(session, row.text_id)
    token = _find_token(text_row, payload.token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Unknown token.")
    if not token["is_word"]:
        # Particles/auxiliaries are not tappable in the text at all (brief);
        # this is a defensive 422 in case the client ever asks anyway.
        raise HTTPException(
            status_code=422, detail="This token is a grammar particle, not a lookup-able word."
        )

    await _log_help(
        session,
        row,
        kind="word_lookup",
        token_id=payload.token_id,
        target=token["lemma"],
        lemma=token["lemma"],
        surface=token["surface"],
    )

    config = await load_runtime_config(session)
    entry = dictionary.lookup(token["lemma"], _lemma_reading(token))
    known_status = await _known_status(config.kanji_trainer_mcp_url, token["lemma"])

    return WordLookupOut(
        surface=token["surface"],
        lemma=token["lemma"],
        reading=_lemma_reading(token),
        jlpt=token["jlpt"],
        meanings=list(entry.glosses[:3]) if entry else [],
        known_status=known_status,
    )


# --- LLM helps: explain / translate / grammar (issue #10) -------------------


def _sentence_for_token(text_row: GeneratedText, token: dict) -> Sentence:
    """The sentence containing `token`, via `sentences.py` -- `token["id"]`'s
    own `"<paragraph>-<token>"` shape (`analysis.py`) names the paragraph to
    split without scanning every one of them."""
    paragraph_index = int(token["id"].split("-", 1)[0])
    paragraph_tokens = text_row.analysis["paragraphs"][paragraph_index]["tokens"]
    pairs = [(t["id"], t["surface"]) for t in paragraph_tokens]
    sentence = find_sentence(paragraph_index, pairs, token["id"])
    assert sentence is not None  # every token belongs to some sentence
    return sentence


def _resolve_span_for_text(
    text_row: GeneratedText, start_token_id: str, end_token_id: str
) -> Span | None:
    """`sentences.resolve_span`, given only the text row and the two token
    ids -- resolves the paragraph from `start_token_id`'s own
    `"<paragraph>-<n>"` shape (same convention `_sentence_for_token` reads)
    and builds the `(id, surface, is_word)` triples it needs. Shared by
    `assist`'s `translate_part`/`grammar_part`, the tutor chat's own span
    focus, and that chat's history replay (issue #32)."""
    paragraph_index = int(start_token_id.split("-", 1)[0])
    paragraphs = text_row.analysis["paragraphs"]
    if paragraph_index < 0 or paragraph_index >= len(paragraphs):
        return None
    paragraph_tokens = paragraphs[paragraph_index]["tokens"]
    triples = [(t["id"], t["surface"], t["is_word"]) for t in paragraph_tokens]
    return resolve_span(paragraph_index, triples, start_token_id, end_token_id)


def _sentence_texts(text_row: GeneratedText) -> dict[str, str]:
    """Every sentence of the text by key, for re-adding a past question's
    focus to the chat history."""
    texts: dict[str, str] = {}
    for paragraph_index, paragraph in enumerate(text_row.analysis["paragraphs"]):
        pairs = [(t["id"], t["surface"]) for t in paragraph["tokens"]]
        for sentence in split_sentences(paragraph_index, pairs):
            texts[sentence.key] = sentence.text
    return texts


def _answered_history(
    text_row: GeneratedText, rows: list[ChatMessage]
) -> list[tuple[str, str]]:
    """The conversation as the model should see it: only questions that got
    an answer (a failed one is kept for the learner, but resending it must
    not reach the model twice, or as two user turns in a row), each with
    its focus -- a sentence, or (issue #32) a span within one -- prefixed
    again exactly as it was when asked.

    `message.focus_sentence_key` is a plain sentence key for a
    whole-sentence focus, or (issue #32) a `sentences.span_target` string
    for a span one -- `parse_span_target` tells the two apart; a span's
    own text is re-resolved from its two token ids (`_resolve_span_for_
    text`) the same way a plain sentence's is looked up by key, never
    stored redundantly.
    """
    sentence_texts: dict[str, str] | None = None
    pairs: list[tuple[str, str]] = []
    for index, message in enumerate(rows):
        if message.role != "user":
            continue
        reply = rows[index + 1] if index + 1 < len(rows) else None
        if reply is None or reply.role != "assistant":
            continue
        question = message.content
        if message.focus_sentence_key:
            parsed = parse_span_target(message.focus_sentence_key)
            if parsed is not None:
                _, start_id, end_id = parsed
                span = _resolve_span_for_text(text_row, start_id, end_id)
                if span is not None:
                    question = focus_question_part(question, span.text, span.sentence.text)
            else:
                if sentence_texts is None:
                    sentence_texts = _sentence_texts(text_row)
                focus = sentence_texts.get(message.focus_sentence_key)
                if focus:
                    question = focus_question(question, focus)
        pairs.append(("user", question))
        pairs.append(("assistant", reply.content))
    return pairs


@router.post("/{session_id}/assist", response_model=AssistResult)
async def assist(
    session_id: int, payload: AssistRequest, session: AsyncSession = Depends(get_session)
) -> AssistResult:
    """Explain word / Translate sentence / Explain grammar, and their
    partial-sentence counterparts Translate part / Explain grammar
    (issue #32). `explain` acts on the tapped word itself (422 on a
    particle); `translate`/`grammar` act on the sentence containing it
    (`_sentence_for_token`); `translate_part`/`grammar_part` act on the
    span from `token_id` to `end_token_id` instead (`sentences.
    resolve_span`, via `_resolve_span_for_text`) -- 422 with a clear
    message if `end_token_id` is missing, the two tokens are not in the
    same sentence, start comes after end, or the inclusive span has fewer
    than two word tokens.

    Cached by `(text_id, kind, target)` in `help_answers`: a cache hit never
    calls OpenAI, and the help event logged for it (see `_log_help`) costs
    this session `0.0` either way -- only an answer this session's own
    request actually generates carries the real cost (`HelpEvent.cost_usd`'s
    docstring).
    """
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "reading")
    text_row = await _get_text_or_404(session, row.text_id)
    token = _find_token(text_row, payload.token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Unknown token.")

    if payload.kind == "explain" and not token["is_word"]:
        raise HTTPException(
            status_code=422,
            detail="This token is a grammar particle, it cannot be explained as a word.",
        )

    span: Span | None = None
    if payload.kind in ("translate_part", "grammar_part"):
        if payload.end_token_id is None:
            raise HTTPException(
                status_code=422,
                detail="end_token_id is required for translate_part/grammar_part.",
            )
        if _find_token(text_row, payload.end_token_id) is None:
            raise HTTPException(status_code=404, detail="Unknown end token.")
        span = _resolve_span_for_text(text_row, payload.token_id, payload.end_token_id)
        if span is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Select a span of at least two words within one sentence, "
                    "start before end."
                ),
            )
        sentence = span.sentence
        target = span_target(sentence.key, span.start_token_id, span.end_token_id)
    else:
        sentence = _sentence_for_token(text_row, token)
        # "Explain word" explains the word *in this sentence*, so its target
        # is the word within its sentence: the same lemma elsewhere in the
        # text is a different question with a different answer.
        target = (
            f"{sentence.key}:{token['lemma']}" if payload.kind == "explain" else sentence.key
        )

    cached_row = await session.scalar(
        select(HelpAnswer).where(
            HelpAnswer.text_id == text_row.id,
            HelpAnswer.kind == payload.kind,
            HelpAnswer.target == target,
        )
    )

    if cached_row is not None:
        help_result = await _log_help(
            session,
            row,
            kind=payload.kind,
            token_id=payload.token_id,
            target=target,
            lemma=token["lemma"],
            surface=token["surface"],
            cost_usd=0.0,
        )
        return AssistResult(
            kind=payload.kind,
            answer=cached_row.answer,
            cached=True,
            counted=help_result.counted,
            weight=help_result.weight,
        )

    config = await load_runtime_config(session)
    if payload.kind == "explain":
        prompt = build_explain_word_instructions(
            text=text_row.body, surface=token["surface"], sentence=sentence.text
        )
    elif payload.kind == "translate":
        prompt = build_translate_sentence_instructions(text=text_row.body, sentence=sentence.text)
    elif payload.kind == "grammar":
        prompt = build_explain_grammar_instructions(text=text_row.body, sentence=sentence.text)
    elif payload.kind == "translate_part":
        assert span is not None  # guaranteed by the branch above
        prompt = build_translate_part_instructions(
            text=text_row.body, span=span.text, sentence=sentence.text
        )
    else:  # "grammar_part"
        assert span is not None  # guaranteed by the branch above
        prompt = build_explain_grammar_part_instructions(
            text=text_row.body, span=span.text, sentence=sentence.text
        )

    try:
        answer, usage = await generate_help_answer(config=config, prompt=prompt)
    except GenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    answer_cost = cost_usd(config.help_model, [usage])

    insert_stmt = (
        postgresql_insert(HelpAnswer)
        .values(
            text_id=text_row.id,
            kind=payload.kind,
            target=target,
            answer=answer,
            model=config.help_model,
            usage=usage.as_dict(),
            cost_usd=answer_cost,
        )
        .on_conflict_do_nothing(index_elements=["text_id", "kind", "target"])
    )
    await session.execute(insert_stmt)
    await session.commit()

    help_result = await _log_help(
        session,
        row,
        kind=payload.kind,
        token_id=payload.token_id,
        target=target,
        lemma=token["lemma"],
        surface=token["surface"],
        cost_usd=answer_cost,
    )

    return AssistResult(
        kind=payload.kind,
        answer=answer,
        cached=False,
        counted=help_result.counted,
        weight=help_result.weight,
    )


# --- Tutor chat (issue #11) --------------------------------------------------


def _chat_message_out(row: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=row.id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        focus_sentence_key=row.focus_sentence_key,
        model=row.model,
        cost_usd=row.cost_usd,
        created_at=row.created_at,
    )


@router.get("/{session_id}/chat", response_model=list[ChatMessageOut])
async def get_chat(session_id: int, session: AsyncSession = Depends(get_session)) -> list[ChatMessageOut]:
    """The session's whole conversation so far, oldest first -- for a reload
    to pick the panel back up where it left off. Available regardless of
    the session's own status (unlike `POST .../chat`): the panel itself is
    never shown outside `reading`, but there is no reason to 404 a read of
    history that still exists once the session moves on."""
    await _get_session_or_404(session, session_id)
    rows = list(
        await session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        )
    )
    return [_chat_message_out(row) for row in rows]


@router.post("/{session_id}/chat", response_model=ChatResult)
async def post_chat(
    session_id: int, payload: ChatRequest, session: AsyncSession = Depends(get_session)
) -> ChatResult:
    """One tutor-chat question. The user message is stored *before* calling
    OpenAI and kept even if that call fails (409 no key, 502 upstream) --
    same convention as `/assist` -- so the client can show it as a failed
    question and let the learner resend (a resend is simply a new question,
    there is nothing to retry server-side).

    `focus_end_token_id` (issue #32) turns the focus into a span rather
    than the whole sentence containing `focus_token_id` -- validated the
    same way `/assist`'s `translate_part`/`grammar_part` are (`sentences.
    resolve_span`): same sentence, start before end, >= 2 word tokens,
    else 422. `ChatMessage.focus_sentence_key` then stores the span target
    (`sentences.span_target`) rather than a plain sentence key -- see that
    function's own docstring for why this needs no schema change.

    Every question is its own help event (`kind: "tutor"`, weight 3,
    `target: "chat:<user message id>"`, always unique) -- counted every
    time, never deduped the way a word/sentence target is (brief: "a
    conversation is not a cacheable question"); the span counts no
    differently from a whole-sentence focus here (brief, issue #32: "Ask
    tutor" stays +3 either way).
    """
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "reading")
    text_row = await _get_text_or_404(session, row.text_id)

    focus_sentence_key: str | None = None
    focus_sentence_text: str | None = None
    focus_span_text: str | None = None
    focus_token: dict | None = None
    if payload.focus_token_id is not None:
        focus_token = _find_token(text_row, payload.focus_token_id)
        if focus_token is None:
            raise HTTPException(status_code=404, detail="Unknown token.")

        if payload.focus_end_token_id is not None:
            if _find_token(text_row, payload.focus_end_token_id) is None:
                raise HTTPException(status_code=404, detail="Unknown end token.")
            span = _resolve_span_for_text(
                text_row, payload.focus_token_id, payload.focus_end_token_id
            )
            if span is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Select a span of at least two words within one sentence, "
                        "start before end."
                    ),
                )
            focus_sentence_key = span_target(
                span.sentence.key, span.start_token_id, span.end_token_id
            )
            focus_sentence_text = span.sentence.text
            focus_span_text = span.text
        else:
            focus_sentence = _sentence_for_token(text_row, focus_token)
            focus_sentence_key = focus_sentence.key
            focus_sentence_text = focus_sentence.text

    history_rows = list(
        await session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        )
    )
    history_pairs = _answered_history(text_row, history_rows)

    user_row = ChatMessage(
        session_id=row.id,
        role="user",
        content=payload.content,
        focus_sentence_key=focus_sentence_key,
    )
    session.add(user_row)
    await session.commit()
    await session.refresh(user_row)

    messages = build_tutor_messages(
        text=text_row.body,
        history=history_pairs,
        question=payload.content,
        focus_sentence=focus_sentence_text,
        focus_span=focus_span_text,
    )

    config = await load_runtime_config(session)
    try:
        answer, usage = await generate_chat_answer(config=config, messages=messages)
    except GenerationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    answer_cost = cost_usd(config.help_model, [usage])
    assistant_row = ChatMessage(
        session_id=row.id,
        role="assistant",
        content=answer,
        model=config.help_model,
        usage=usage.as_dict(),
        cost_usd=answer_cost,
    )
    session.add(assistant_row)
    await session.commit()
    await session.refresh(assistant_row)

    help_result = await _log_help(
        session,
        row,
        kind="tutor",
        token_id=focus_token["id"] if focus_token else "",
        target=f"chat:{user_row.id}",
        lemma=focus_token["lemma"] if focus_token else "",
        surface=focus_token["surface"] if focus_token else "",
        cost_usd=answer_cost,
    )

    return ChatResult(
        user_message=_chat_message_out(user_row),
        assistant_message=_chat_message_out(assistant_row),
        counted=help_result.counted,
        weight=help_result.weight,
    )


@router.post("/{session_id}/finish-reading", response_model=SessionOut)
async def finish_reading(
    session_id: int, payload: FinishReadingRequest, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "reading")
    row.active_ms = max(row.active_ms, payload.active_ms)
    row.paused_ms = max(row.paused_ms, payload.paused_ms)
    row.status = "questions"
    row.reading_finished_at = datetime.now(timezone.utc)
    await session.commit()
    text_row = await _get_text_or_404(session, row.text_id)
    return _session_out(row, text_row)


def _qualifies_for_stretch_adjustment(text_row: GeneratedText) -> bool:
    """Issue #13's brief: only a session whose text was generated with
    preset `stretch` and *no* JLPT-mix/unknown-kanji overrides -- both
    flags come from `api/texts.py`'s own `params["overrides_used"]`,
    absent (`.get(..., {})`) for any text generated before issue #13, which
    reads the same as "no overrides" (correctly: those rows predate
    overrides even being tracked here, but *did* always use the then-static
    preset untouched)."""
    params = text_row.params
    if params.get("preset") != "stretch":
        return False
    overrides_used = params.get("overrides_used") or {}
    return not overrides_used.get("unknown_kanji_target") and not overrides_used.get("jlpt_mix")


async def _text_read_before(session: AsyncSession, row: ReadingSession) -> bool:
    """Whether another session already finished this session's text."""
    earlier = await session.scalar(
        select(ReadingSession.id)
        .where(
            ReadingSession.text_id == row.text_id,
            ReadingSession.status == "finished",
            ReadingSession.id != row.id,
        )
        .limit(1)
    )
    return earlier is not None


async def _apply_stretch_adjustment(
    session: AsyncSession, row: ReadingSession, text_row: GeneratedText, questions: list[dict]
) -> None:
    """Runs the rule and records one `stretch_adjustments` row, in the same
    transaction `answer_question` commits once it returns -- idempotent per
    session (`stretch_store.record_adjustment`'s own `ON CONFLICT DO
    NOTHING`), so a caller that somehow ran this twice for the same session
    would simply no-op the second time."""
    metrics = text_row.analysis["metrics"]
    weight_sum = await session.scalar(
        select(func.sum(HelpEvent.weight)).where(HelpEvent.session_id == row.id)
    )
    helps = _helps_per_100_words(weight_sum or 0, metrics["words"])
    comprehension = (
        round((row.comprehension_correct or 0) / len(questions) * 100, 1) if questions else 0.0
    )

    d_before = await stretch_store.current_d(session)
    result = stretch.adjust(
        d_before, helps_per_100_words=helps, comprehension_percent=comprehension
    )
    await stretch_store.record_adjustment(
        session,
        reading_session_id=row.id,
        d_before=result.d_before,
        d_after=result.d_after,
        helps_per_100_words=helps,
        comprehension=comprehension,
        reason=result.reason,
    )


@router.post("/{session_id}/answers", response_model=AnswerResult)
async def answer_question(
    session_id: int, payload: AnswerRequest, session: AsyncSession = Depends(get_session)
) -> AnswerResult:
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "questions")
    text_row = await _get_text_or_404(session, row.text_id)
    questions = text_row.questions
    if not (0 <= payload.question_index < len(questions)):
        raise HTTPException(status_code=404, detail="Unknown question.")

    answers = list(row.answers)
    if answers[payload.question_index] is not None:
        raise HTTPException(status_code=409, detail="This question has already been answered.")

    correct_index = questions[payload.question_index]["answer_index"]
    answers[payload.question_index] = payload.option_index
    row.answers = answers  # reassignment, not in-place mutation -- JSONB

    if all(answer is not None for answer in answers):
        row.status = "finished"
        row.finished_at = datetime.now(timezone.utc)
        row.comprehension_correct = sum(
            1 for i in range(len(questions)) if answers[i] == questions[i]["answer_index"]
        )

        # Issue #13: nudge Stretch's own difficulty, in this same
        # transaction -- see `_qualifies_for_stretch_adjustment`'s
        # docstring for exactly which sessions this applies to.
        # A re-read of the same text never moves it: it is easier for reasons
        # that say nothing about the level (same rule as the reading pace).
        if _qualifies_for_stretch_adjustment(text_row) and not await _text_read_before(
            session, row
        ):
            await _apply_stretch_adjustment(session, row, text_row, questions)

    await session.commit()
    return AnswerResult(correct=payload.option_index == correct_index, correct_index=correct_index)


@router.get("/{session_id}/summary", response_model=SessionSummaryOut)
async def get_summary(
    session_id: int, session: AsyncSession = Depends(get_session)
) -> SessionSummaryOut:
    row = await _get_session_or_404(session, session_id)
    _require_status(row, "finished")
    text_row = await _get_text_or_404(session, row.text_id)
    metrics = text_row.analysis["metrics"]

    active_minutes = row.active_ms / 60_000
    chars_per_minute = round(metrics["characters"] / active_minutes) if active_minutes > 0 else 0
    words_per_minute = round(metrics["words"] / active_minutes) if active_minutes > 0 else 0

    help_rows = list(
        await session.scalars(
            select(HelpEvent)
            .where(HelpEvent.session_id == session_id)
            .order_by(HelpEvent.created_at, HelpEvent.id)
        )
    )
    weight_sum = sum(h.weight for h in help_rows)
    helps_per_100_words = _helps_per_100_words(weight_sum, metrics["words"])
    # 0.0 for reading_peek/word_lookup (cost_usd is NULL) and for a cached
    # assist answer (cost_usd is 0.0) alike -- only an assist/chat this
    # session's own request actually generated adds anything (see
    # `HelpEvent.cost_usd`). A tutor-chat answer is never cached, but its
    # cost sums in here exactly the same way.
    assists_cost_usd = sum(h.cost_usd or 0.0 for h in help_rows)
    chat_questions = sum(1 for h in help_rows if h.kind == "tutor")

    questions = text_row.questions
    answers = row.answers
    questions_correct = sum(
        1
        for index, answer in enumerate(answers)
        if answer is not None and index < len(questions) and answer == questions[index]["answer_index"]
    )

    looked_up_words: list[LookedUpWordOut] = []
    for help_row in help_rows:
        if help_row.kind != "word_lookup":
            continue
        token = _find_token(text_row, help_row.token_id)
        reading = _lemma_reading(token) if token else ""
        entry = dictionary.lookup(help_row.lemma, reading) if token else None
        meaning = entry.glosses[0] if entry and entry.glosses else ""
        looked_up_words.append(LookedUpWordOut(word=help_row.lemma, reading=reading, meaning=meaning))

    # Issue #13: the summary's one quiet line, only when this session
    # actually moved Stretch -- never for "unchanged" (still its own row in
    # `stretch_adjustments`, just nothing the learner needs reading about).
    stretch_row = await session.scalar(
        select(StretchAdjustment).where(StretchAdjustment.session_id == session_id)
    )
    stretch_adjustment = (
        stretch_row.reason if stretch_row is not None and stretch_row.reason != "unchanged" else None
    )

    return SessionSummaryOut(
        chars_per_minute=chars_per_minute,
        words_per_minute=words_per_minute,
        helps_per_100_words=helps_per_100_words,
        questions_correct=questions_correct,
        questions_total=len(questions),
        active_ms=row.active_ms,
        looked_up_words=looked_up_words,
        assists_cost_usd=assists_cost_usd,
        chat_questions=chat_questions,
        stretch_adjustment=stretch_adjustment,  # type: ignore[arg-type]
    )


@pace_router.get("/pace", response_model=ReadingPaceOut)
async def get_pace(session: AsyncSession = Depends(get_session)) -> ReadingPaceOut:
    """Median chars/min over the last `PACE_SAMPLE_SESSIONS` finished
    sessions, default `DEFAULT_CHARS_PER_MINUTE` until at least
    `PACE_MIN_SESSIONS` exist -- the setup screen's duration estimate and
    the gate's own estimate both read this."""
    # Only each text's first finished read: reading the same text again is
    # faster for reasons that say nothing about the reader's pace.
    first_reads = (
        select(ReadingSession.id)
        .where(ReadingSession.status == "finished")
        .distinct(ReadingSession.text_id)
        .order_by(ReadingSession.text_id, ReadingSession.finished_at)
    )
    rows = list(
        await session.scalars(
            select(ReadingSession)
            .where(ReadingSession.id.in_(first_reads))
            .order_by(ReadingSession.finished_at.desc())
            .limit(PACE_SAMPLE_SESSIONS)
        )
    )

    rates: list[float] = []
    for row in rows:
        if row.active_ms <= 0:
            continue
        text_row = await session.get(GeneratedText, row.text_id)
        if text_row is None:
            continue
        characters = text_row.analysis["metrics"]["characters"]
        rates.append(characters / (row.active_ms / 60_000))

    if len(rates) < PACE_MIN_SESSIONS:
        return ReadingPaceOut(
            chars_per_minute=DEFAULT_CHARS_PER_MINUTE, source="default", sessions=len(rates)
        )

    return ReadingPaceOut(
        chars_per_minute=round(statistics.median(rates)), source="history", sessions=len(rates)
    )
