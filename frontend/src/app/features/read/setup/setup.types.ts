// `sumi-share-slider` (sumi-ui#99, `sumi-ui/forms`) replaced
// `proto/jlpt-multi-slider`; it works with a plain labelled array
// (`SumiShareSegment[]`), not this app's own keyed `JlptShares`, so
// `jlptSharesToSegments`/`segmentsToJlptShares` below bridge the two at
// the one place that binds to it (`SetupScreen`) — every other consumer
// (`DIFFICULTY_PRESETS`, `GateScreen`, the preview fixtures) keeps using
// the keyed shape, which is far more convenient to read/construct by level.
import type { SumiShareSegment } from 'sumi-ui/forms';

export interface JlptShares {
  n5: number;
  n4: number;
  n3: number;
  n2: number;
  n1: number;
}

export type ReadingLength = 'short' | 'medium' | 'long';
export type DifficultyPreset = 'easy' | 'stretch' | 'challenge';
export type TextStyle = 'casual' | 'polite' | 'formal';

/** 文字 per length, see REQUIREMENTS.md / the concept. */
export const READING_LENGTH_CHARS: Record<ReadingLength, number> = {
  short: 300,
  medium: 600,
  long: 1000,
};

export const READING_LENGTH_LABELS: Record<ReadingLength, string> = {
  short: 'Short',
  medium: 'Medium',
  long: 'Long',
};

export interface DifficultySettings {
  unknownKanjiSharePercent: number;
  jlptMix: JlptShares;
  style: TextStyle;
}

/**
 * The three presets' own settings — "Stretch" additionally adapts after
 * every session (see the one-line note under the control), which this
 * table does not capture since it is behaviour, not a starting value.
 *
 * These numbers match the backend's own `presets.py` (`unknown_kanji_target`
 * as a percent, `jlpt_mix` as shares out of 100) -- issue #9's wiring: a
 * preset chosen without opening "Adjust" sends no `overrides` at all and
 * lets the backend's own preset apply, so what this screen promises before
 * generating and what the gate actually measures have to agree. `style`
 * has no backend equivalent (the backend's own presets leave it `None` --
 * the *topic's* `default_style` wins unless overridden); kept here only so
 * the summary line and the "Adjust" control have something to show, and
 * never sent unless the learner actually opens "Adjust" and changes it.
 */
export const DIFFICULTY_PRESETS: Record<DifficultyPreset, DifficultySettings> = {
  easy: {
    unknownKanjiSharePercent: 2,
    jlptMix: { n5: 70, n4: 30, n3: 0, n2: 0, n1: 0 },
    style: 'polite',
  },
  stretch: {
    unknownKanjiSharePercent: 5,
    jlptMix: { n5: 50, n4: 35, n3: 15, n2: 0, n1: 0 },
    style: 'polite',
  },
  challenge: {
    unknownKanjiSharePercent: 10,
    jlptMix: { n5: 30, n4: 35, n3: 25, n2: 10, n1: 0 },
    style: 'formal',
  },
};

const JLPT_ORDER: (keyof JlptShares)[] = ['n5', 'n4', 'n3', 'n2', 'n1'];
const JLPT_LABELS: Record<keyof JlptShares, string> = {
  n5: 'N5',
  n4: 'N4',
  n3: 'N3',
  n2: 'N2',
  n1: 'N1',
};

/** "Mostly N5–N4 · up to 5% unknown kanji · polite" — the one-line summary
 *  shown under the collapsed difficulty control. */
export function summarizeDifficulty(settings: DifficultySettings): string {
  const byShareDesc = [...JLPT_ORDER].sort((a, b) => settings.jlptMix[b] - settings.jlptMix[a]);
  const topTwo = byShareDesc.slice(0, 2).filter((level) => settings.jlptMix[level] > 0);
  // Back to level order (N5 → N1), not share order, so "N4–N5" never reads
  // backwards even when N4 happens to have the larger share.
  const inLevelOrder = JLPT_ORDER.filter((level) => topTwo.includes(level));
  const mix =
    inLevelOrder.length === 2
      ? `Mostly ${JLPT_LABELS[inLevelOrder[0]]}–${JLPT_LABELS[inLevelOrder[1]]}`
      : `Mostly ${JLPT_LABELS[inLevelOrder[0] ?? 'n5']}`;
  const styleLabel = settings.style.toLowerCase();
  return `${mix} · up to ${settings.unknownKanjiSharePercent}% unknown kanji · ${styleLabel}`;
}

export function jlptSharesToSegments(shares: JlptShares): SumiShareSegment[] {
  return JLPT_ORDER.map((level) => ({ label: JLPT_LABELS[level], value: shares[level] }));
}

export function segmentsToJlptShares(segments: readonly SumiShareSegment[]): JlptShares {
  const byLabel = new Map(segments.map((segment) => [segment.label, segment.value]));
  const next: JlptShares = { n5: 0, n4: 0, n3: 0, n2: 0, n1: 0 };
  for (const level of JLPT_ORDER) {
    next[level] = byLabel.get(JLPT_LABELS[level]) ?? 0;
  }
  return next;
}
