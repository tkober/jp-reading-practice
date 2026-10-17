import type { SumiBar, SumiLinePoint } from 'sumi-ui/charts';
import type {
  ProblemWordApi,
  SeriesPointApi,
  SpeedByGroupApi,
  StatsSummaryApi,
} from '../../core/api.types';
import type { ProblemWord, StatsSummary } from '../../features/stats/stats.types';

/**
 * The `GET /api/stats` response's pieces -> `StatsScreen`'s own input
 * shapes -- pulled out of `StatsPage` so this plumbing has its own unit
 * test independent of the page's loading/T6 wiring (same reasoning as
 * `pages/history/history-mapping.ts`).
 */
export function toStatsSummary(api: StatsSummaryApi): StatsSummary {
  return {
    speedCharsPerMinute: api.speed_chars_per_minute,
    // Rounded for the tiles: a whole percent for the delta, one decimal for
    // helps and comprehension, like the history table.
    speedDeltaPercent: api.speed_delta_percent == null ? null : Math.round(api.speed_delta_percent),
    helpsPerHundred: Math.round(api.helps_per_100_words * 10) / 10,
    comprehensionPercent: Math.round(api.comprehension_percent * 10) / 10,
    readingLevel: api.reading_level,
    readingLevelDetail: api.reading_level_detail,
  };
}

/** `points` is already oldest-first (the backend's own `speed_series`/
 *  `helps_series` order) -- `key` is the one `sumi-line-chart` series key
 *  (`'speed'`/`'helps'`) this trend is plotted under. */
export function toLinePoints(points: readonly SeriesPointApi[], key: string): SumiLinePoint[] {
  return points.map((point) => ({ date: point.date, values: { [key]: point.value } }));
}

export function toBars(groups: readonly SpeedByGroupApi[]): SumiBar[] {
  return groups.map((group) => ({ label: group.label, value: group.value }));
}

export function toProblemWords(words: readonly ProblemWordApi[]): ProblemWord[] {
  return words.map((word) => ({
    word: word.word,
    reading: word.reading,
    meaning: word.meaning,
    timesLookedUp: word.times_looked_up,
  }));
}
