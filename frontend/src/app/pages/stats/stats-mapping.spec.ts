import { describe, expect, it } from 'vitest';
import { toBars, toLinePoints, toProblemWords, toStatsSummary } from './stats-mapping';

describe('toStatsSummary', () => {
  it('maps every field', () => {
    expect(
      toStatsSummary({
        speed_chars_per_minute: 130,
        speed_delta_percent: 12.4,
        helps_per_100_words: 4.15,
        comprehension_percent: 83.3,
        reading_level: 'N4',
        reading_level_detail: 'comfortable · N3 with help',
      }),
    ).toEqual({
      speedCharsPerMinute: 130,
      speedDeltaPercent: 12,
      helpsPerHundred: 4.2,
      comprehensionPercent: 83.3,
      readingLevel: 'N4',
      readingLevelDetail: 'comfortable · N3 with help',
    });
  });

  it('keeps a null delta (no window to compare against)', () => {
    expect(
      toStatsSummary({
        speed_chars_per_minute: 130,
        speed_delta_percent: null,
        helps_per_100_words: 4,
        comprehension_percent: 83.3,
        reading_level: 'N4',
        reading_level_detail: 'comfortable',
      }).speedDeltaPercent,
    ).toBeNull();
  });
});

describe('toLinePoints', () => {
  it('keys each point by the given series key, oldest first unchanged', () => {
    const points = toLinePoints(
      [
        { date: '2026-09-13', value: 118 },
        { date: '2026-09-16', value: 121 },
      ],
      'speed',
    );
    expect(points).toEqual([
      { date: '2026-09-13', values: { speed: 118 } },
      { date: '2026-09-16', values: { speed: 121 } },
    ]);
  });
});

describe('toBars', () => {
  it('maps label/value straight through', () => {
    expect(toBars([{ label: 'Casual', value: 148 }])).toEqual([{ label: 'Casual', value: 148 }]);
  });
});

describe('toProblemWords', () => {
  it('renames times_looked_up to timesLookedUp', () => {
    expect(
      toProblemWords([
        { word: '伺う', reading: 'うかがう', meaning: 'to visit', times_looked_up: 4 },
      ]),
    ).toEqual([{ word: '伺う', reading: 'うかがう', meaning: 'to visit', timesLookedUp: 4 }]);
  });
});
