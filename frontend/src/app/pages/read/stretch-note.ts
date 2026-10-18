import type { SessionSummaryApi } from '../../core/api.types';

/**
 * The summary screen's one quiet line when a session moved Stretch's own
 * difficulty (issue #13) -- `null` when it did not: not a stretch session,
 * one with a JLPT-mix/unknown-kanji override, or the rule decided
 * "unchanged" (`stretch_adjustment` is `null` for all three on the backend
 * already, see `SessionSummaryOut`'s own docstring).
 */
export function stretchNoteText(reason: SessionSummaryApi['stretch_adjustment']): string | null {
  if (reason === 'harder') {
    return 'Stretch is now a little harder.';
  }
  if (reason === 'easier') {
    return 'Stretch is now a little easier.';
  }
  return null;
}
