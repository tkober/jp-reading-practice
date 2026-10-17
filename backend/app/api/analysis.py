"""`POST /api/analysis` -- the debug endpoint for development and #8.

Fetches the live known set and JLPT levels via MCP and calls the pure
`analyze()`. If the Kanji Trainer is unreachable, degrades to analysing with
an empty known set and no JLPT levels (every kanji looks unknown, every
word's `jlpt` is `null`) rather than failing the request -- the same
"something is still better than nothing" choice `GET
/api/kanji-trainer/status` makes, just surfaced as `kanji_trainer_error`
instead of a dedicated status shape, since this endpoint's whole response is
the analysis either way.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import kanji_trainer as kt
from ..analysis import analyze, collect_lemmas
from ..db import get_session
from ..known_set import KnownSet, fetch_known_set
from ..models import AnalysisRequest, AnalysisResponse
from ..runtime_config import load_runtime_config

router = APIRouter()


@router.post("", response_model=AnalysisResponse)
async def analyze_text(
    payload: AnalysisRequest, session: AsyncSession = Depends(get_session)
) -> AnalysisResponse:
    config = await load_runtime_config(session)
    url = config.kanji_trainer_mcp_url

    error: str | None = None
    try:
        known = await fetch_known_set(url)
    except kt.KanjiTrainerUnavailable as exc:
        known = KnownSet()
        error = str(exc)

    jlpt_lookup: dict[tuple[str, str | None], kt.JlptLevelResult] = {}
    if error is None:
        lemma_keys = collect_lemmas(payload.text)
        if lemma_keys:
            try:
                results = await kt.get_jlpt_levels(
                    url, [kt.JlptQuery(text=lemma, reading=reading) for lemma, reading in lemma_keys]
                )
                jlpt_lookup = dict(zip(lemma_keys, results, strict=True))
            except kt.KanjiTrainerUnavailable as exc:
                error = str(exc)

    analysis = analyze(payload.text, known, jlpt_lookup)
    return AnalysisResponse(paragraphs=analysis.paragraphs, metrics=analysis.metrics, kanji_trainer_error=error)
