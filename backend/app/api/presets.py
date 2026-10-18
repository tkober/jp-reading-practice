"""`GET /api/presets` (issue #13): the three presets' resolved generation
targets -- `easy`/`challenge` straight from `app.presets`' static table,
`stretch` resolved at its current difficulty (`app.stretch_store.current_d`
-> `app.stretch.resolve`), plus that difficulty itself and the most recent
adjustment's reason/date. The setup screen reads this instead of its own
hard-coded `DIFFICULTY_PRESETS` table for the preset descriptions and the
"Adjust" defaults (that table stays only as the offline fallback/preview
fixture, per the brief).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import presets as difficulty_presets
from .. import stretch, stretch_store
from ..db import get_session
from ..models import JlptMixTarget, PresetOut, PresetsOut, StretchAdjustmentNoteOut, StretchPresetOut

router = APIRouter()


def _static_preset_out(name: str) -> PresetOut:
    preset = difficulty_presets.get_preset(name)
    assert preset is not None  # "easy"/"challenge" are always built in
    return PresetOut(unknown_kanji_target=preset.unknown_kanji_target, jlpt_mix=preset.jlpt_mix)


@router.get("", response_model=PresetsOut)
async def get_presets(session: AsyncSession = Depends(get_session)) -> PresetsOut:
    latest = await stretch_store.latest_adjustment(session)
    d = latest.d_after if latest is not None else stretch.D_START
    mix = stretch.resolve(d)

    last_adjustment = (
        StretchAdjustmentNoteOut(reason=latest.reason, created_at=latest.created_at)  # type: ignore[arg-type]
        if latest is not None
        else None
    )

    return PresetsOut(
        easy=_static_preset_out("easy"),
        stretch=StretchPresetOut(
            unknown_kanji_target=mix.unknown_kanji_target,
            jlpt_mix=JlptMixTarget(**mix.jlpt_mix),
            d=d,
            last_adjustment=last_adjustment,
        ),
        challenge=_static_preset_out("challenge"),
    )
