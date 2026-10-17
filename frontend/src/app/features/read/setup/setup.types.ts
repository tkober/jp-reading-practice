import type { JlptShares } from '../../../proto/jlpt-multi-slider/jlpt-multi-slider';

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

/** The three presets' own settings — "Stretch" additionally adapts after
 *  every session (see the one-line note under the control), which this
 *  table does not capture since it is behaviour, not a starting value. */
export const DIFFICULTY_PRESETS: Record<DifficultyPreset, DifficultySettings> = {
  easy: {
    unknownKanjiSharePercent: 2,
    jlptMix: { n5: 70, n4: 25, n3: 5, n2: 0, n1: 0 },
    style: 'polite',
  },
  stretch: {
    unknownKanjiSharePercent: 5,
    jlptMix: { n5: 50, n4: 35, n3: 15, n2: 0, n1: 0 },
    style: 'polite',
  },
  challenge: {
    unknownKanjiSharePercent: 12,
    jlptMix: { n5: 20, n4: 30, n3: 35, n2: 15, n1: 0 },
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
  const byShareDesc = [...JLPT_ORDER].sort(
    (a, b) => settings.jlptMix[b] - settings.jlptMix[a],
  );
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
