import type { SuggestionApi } from '../../../core/api.types';
import type { DifficultyPreset, JlptShares, ReadingLength, TextStyle } from './setup.types';

/**
 * What "Use this" applies to the setup screen's controls (issue #14) --
 * pure and framework-free so it can be unit tested on its own, same split
 * as `token-mapping.ts`/`stretch-note.ts` elsewhere in this app.
 *
 * `unknownKanjiSharePercent`/`jlptMix`/`style` are `undefined` exactly when
 * the suggestion did not override that field -- the caller (`ReadPage`)
 * then keeps whatever the chosen preset's own default already is, the same
 * "only a touched field ever becomes an override" rule `onPresetChange`
 * already follows. `adjustOpen` is `true` iff at least one of the three is
 * set, per the brief ("Adjust opened when there are any").
 */
export interface AppliedSuggestion {
  topicId: string;
  length: ReadingLength;
  preset: DifficultyPreset;
  unknownKanjiSharePercent?: number;
  jlptMix?: JlptShares;
  style?: TextStyle;
  adjustOpen: boolean;
}

function roundPercent(fraction: number): number {
  return Math.round(fraction * 100);
}

/**
 * Turn a `SuggestionApi` (fractions 0..1, the backend's own convention)
 * into what the setup screen's controls want (percent integers) -- never
 * generates anything itself, "Use this" only populates the controls (brief:
 * "applies everything to the setup controls ... but does not generate
 * yet").
 */
export function applySuggestionToSetup(suggestion: SuggestionApi): AppliedSuggestion {
  const overrides = suggestion.overrides;

  const unknownKanjiSharePercent =
    overrides?.unknown_kanji_target != null
      ? roundPercent(overrides.unknown_kanji_target)
      : undefined;

  const jlptMix = overrides?.jlpt_mix
    ? {
        n5: roundPercent(overrides.jlpt_mix.n5 ?? 0),
        n4: roundPercent(overrides.jlpt_mix.n4 ?? 0),
        n3: roundPercent(overrides.jlpt_mix.n3 ?? 0),
        n2: roundPercent(overrides.jlpt_mix.n2 ?? 0),
        n1: roundPercent(overrides.jlpt_mix.n1 ?? 0),
      }
    : undefined;

  const style = overrides?.style ?? undefined;

  return {
    topicId: suggestion.topic_slug,
    length: suggestion.length,
    preset: suggestion.preset,
    unknownKanjiSharePercent,
    jlptMix,
    style,
    adjustOpen:
      unknownKanjiSharePercent !== undefined || jlptMix !== undefined || style !== undefined,
  };
}
