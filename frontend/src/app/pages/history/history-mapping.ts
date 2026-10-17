import type { HistoryEntryApi } from '../../core/api.types';
import { READING_LENGTH_LABELS } from '../../features/read/setup/setup.types';
import type { HistorySession } from '../../features/history/history.types';

/**
 * `"2026-09-13"` -> `"Sep 13"` -- matches the approved design's own fixture
 * convention (`preview/fixtures/history.fixture.ts`): no year, since a
 * history list realistically spans weeks, not years.
 */
export function formatHistoryDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * `GET /api/history`'s row -> `HistoryScreen`'s own input shape -- pulled
 * out of `HistoryPage` so the one non-trivial decision here (the backend's
 * `null`s for an unfinished session map straight through, `HistorySession.
 * finished` is what the screen keys "In progress" off of) has its own unit
 * test independent of the page's loading/T6 wiring.
 */
export function toHistorySession(entry: HistoryEntryApi): HistorySession {
  return {
    id: String(entry.id),
    date: formatHistoryDate(entry.date),
    titleJapanese: entry.title,
    topicName: entry.topic_name,
    length: READING_LENGTH_LABELS[entry.length] as HistorySession['length'],
    finished: entry.finished,
    speedCharsPerMinute: entry.speed_chars_per_minute,
    helpsPerHundred: entry.helps_per_100_words,
    scoreCorrect: entry.comprehension_correct,
    scoreTotal: entry.comprehension_total,
  };
}
