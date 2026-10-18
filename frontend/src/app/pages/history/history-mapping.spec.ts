import { describe, expect, it } from 'vitest';
import type { HistoryEntryApi } from '../../core/api.types';
import { formatHistoryDate, toHistorySession } from './history-mapping';

function entry(overrides: Partial<HistoryEntryApi> = {}): HistoryEntryApi {
  return {
    id: 1,
    date: '2026-09-13',
    title: '休みの日の過ごし方',
    topic_name: 'Daily life',
    length: 'short',
    finished: true,
    speed_chars_per_minute: 120,
    helps_per_100_words: 8,
    comprehension_correct: 2,
    comprehension_total: 3,
    ...overrides,
  };
}

describe('formatHistoryDate', () => {
  it('formats an ISO date as "Mon D", no year', () => {
    expect(formatHistoryDate('2026-09-13')).toBe('Sep 13');
    expect(formatHistoryDate('2026-01-02')).toBe('Jan 2');
  });
});

describe('toHistorySession', () => {
  it('maps a finished entry straight through', () => {
    const session = toHistorySession(entry());
    expect(session).toEqual({
      id: '1',
      date: 'Sep 13',
      titleJapanese: '休みの日の過ごし方',
      topicName: 'Daily life',
      length: 'Short',
      finished: true,
      speedCharsPerMinute: 120,
      helpsPerHundred: 8,
      scoreCorrect: 2,
      scoreTotal: 3,
    });
  });

  it('nulls every number for an unfinished session', () => {
    const session = toHistorySession(
      entry({
        finished: false,
        speed_chars_per_minute: null,
        helps_per_100_words: null,
        comprehension_correct: null,
        comprehension_total: null,
      }),
    );
    expect(session.finished).toBe(false);
    expect(session.speedCharsPerMinute).toBeNull();
    expect(session.helpsPerHundred).toBeNull();
    expect(session.scoreCorrect).toBeNull();
    expect(session.scoreTotal).toBeNull();
  });

  it('maps every length to its label', () => {
    expect(toHistorySession(entry({ length: 'medium' })).length).toBe('Medium');
    expect(toHistorySession(entry({ length: 'long' })).length).toBe('Long');
  });
});
