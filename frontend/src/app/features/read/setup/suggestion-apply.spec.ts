import { describe, expect, it } from 'vitest';
import type { SuggestionApi } from '../../../core/api.types';
import { applySuggestionToSetup } from './suggestion-apply';

function suggestion(overrides: Partial<SuggestionApi> = {}): SuggestionApi {
  return {
    id: 1,
    topic_slug: 'travel',
    length: 'medium',
    preset: 'stretch',
    overrides: null,
    reason: 'Your last three Travel texts needed few helps.',
    ...overrides,
  };
}

describe('applySuggestionToSetup', () => {
  it('carries topic/length/preset straight through', () => {
    const applied = applySuggestionToSetup(suggestion());
    expect(applied.topicId).toBe('travel');
    expect(applied.length).toBe('medium');
    expect(applied.preset).toBe('stretch');
  });

  it('leaves every override field and adjustOpen unset when there are none', () => {
    const applied = applySuggestionToSetup(suggestion({ overrides: null }));
    expect(applied.unknownKanjiSharePercent).toBeUndefined();
    expect(applied.jlptMix).toBeUndefined();
    expect(applied.style).toBeUndefined();
    expect(applied.adjustOpen).toBe(false);
  });

  it('converts a style override and opens Adjust', () => {
    const applied = applySuggestionToSetup(
      suggestion({ overrides: { style: 'formal', unknown_kanji_target: null, jlpt_mix: null } }),
    );
    expect(applied.style).toBe('formal');
    expect(applied.unknownKanjiSharePercent).toBeUndefined();
    expect(applied.jlptMix).toBeUndefined();
    expect(applied.adjustOpen).toBe(true);
  });

  it('converts an unknown-kanji fraction to a rounded percent', () => {
    const applied = applySuggestionToSetup(
      suggestion({ overrides: { unknown_kanji_target: 0.08, jlpt_mix: null, style: null } }),
    );
    expect(applied.unknownKanjiSharePercent).toBe(8);
    expect(applied.adjustOpen).toBe(true);
  });

  it('converts a JLPT mix from fractions to whole percents', () => {
    const applied = applySuggestionToSetup(
      suggestion({
        overrides: {
          jlpt_mix: { n5: 0.45, n4: 0.35, n3: 0.2, n2: 0, n1: 0 },
          unknown_kanji_target: null,
          style: null,
        },
      }),
    );
    expect(applied.jlptMix).toEqual({ n5: 45, n4: 35, n3: 20, n2: 0, n1: 0 });
    expect(applied.adjustOpen).toBe(true);
  });

  it('treats a missing JLPT level as 0%', () => {
    const applied = applySuggestionToSetup(
      suggestion({
        overrides: {
          jlpt_mix: { n5: 0.6, n4: 0.4, n3: 0, n2: 0, n1: 0 },
          unknown_kanji_target: null,
          style: null,
        },
      }),
    );
    expect(applied.jlptMix).toEqual({ n5: 60, n4: 40, n3: 0, n2: 0, n1: 0 });
  });

  it('opens Adjust when only one of the three fields is overridden', () => {
    const applied = applySuggestionToSetup(
      suggestion({ overrides: { unknown_kanji_target: 0.1, jlpt_mix: null, style: null } }),
    );
    expect(applied.adjustOpen).toBe(true);
  });

  it('never generates anything by itself -- it only returns setup values', () => {
    const applied = applySuggestionToSetup(suggestion());
    expect(Object.keys(applied)).not.toContain('generate');
  });
});
