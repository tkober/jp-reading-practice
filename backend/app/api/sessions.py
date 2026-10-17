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
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import dictionary
from .. import kanji_trainer as kt
from ..db import GeneratedText, HelpEvent, ReadingSession, get_session
from ..helps import WEIGHTS
from ..models import (
    AnswerRequest,
    AnswerResult,
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
from ..runtime_config import load_runtime_config
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
    lemma: str,
    surface: str,
) -> HelpResult:
    """Insert one help event, deduped by `(session_id, kind, lemma)` -- a
    repeat is a no-op (`counted=False`), never an error."""
    weight = WEIGHTS[kind]
    stmt = (
        postgresql_insert(HelpEvent)
        .values(
            session_id=session_row.id,
            kind=kind,
            token_id=token_id,
            lemma=lemma,
            surface=surface,
            weight=weight,
            at_ms=session_row.active_ms,
        )
        .on_conflict_do_nothing(index_elements=["session_id", "kind", "lemma"])
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
        lemma=token["lemma"],
        surface=token["surface"],
    )

    config = await load_runtime_config(session)
    entry = dictionary.lookup(token["lemma"], token["lemma_reading"])
    known_status = await _known_status(config.kanji_trainer_mcp_url, token["lemma"])

    return WordLookupOut(
        surface=token["surface"],
        lemma=token["lemma"],
        reading=token["lemma_reading"],
        jlpt=token["jlpt"],
        meanings=list(entry.glosses[:3]) if entry else [],
        known_status=known_status,
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
        row.comprehension_correct = all(
            answers[i] == questions[i]["answer_index"] for i in range(len(questions))
        )

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
    helps_per_100_words = (
        round(weight_sum / metrics["words"] * 100, 1) if metrics["words"] else 0.0
    )

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
        reading = token["lemma_reading"] if token else ""
        entry = dictionary.lookup(help_row.lemma, reading) if token else None
        meaning = entry.glosses[0] if entry and entry.glosses else ""
        looked_up_words.append(LookedUpWordOut(word=help_row.lemma, reading=reading, meaning=meaning))

    return SessionSummaryOut(
        chars_per_minute=chars_per_minute,
        words_per_minute=words_per_minute,
        helps_per_100_words=helps_per_100_words,
        questions_correct=questions_correct,
        questions_total=len(questions),
        active_ms=row.active_ms,
        looked_up_words=looked_up_words,
    )


@pace_router.get("/pace", response_model=ReadingPaceOut)
async def get_pace(session: AsyncSession = Depends(get_session)) -> ReadingPaceOut:
    """Median chars/min over the last `PACE_SAMPLE_SESSIONS` finished
    sessions, default `DEFAULT_CHARS_PER_MINUTE` until at least
    `PACE_MIN_SESSIONS` exist -- the setup screen's duration estimate and
    the gate's own estimate both read this."""
    rows = list(
        await session.scalars(
            select(ReadingSession)
            .where(ReadingSession.status == "finished")
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
