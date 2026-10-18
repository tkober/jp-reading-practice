// Preview-only fixture data — not the learner's own data. Derived from
// `HISTORY_SESSIONS`: same slowly-improving speed/helps trend, used for the
// stats screen's line charts.
import type { SumiBar, SumiLinePoint } from 'sumi-ui/charts';
import type { ProblemWord, StatsSummary } from '../../features/stats/stats.types';
import { HISTORY_SESSIONS } from './history.fixture';

/** "Sep 13" → "2026-09-13", so the dates line up with `HISTORY_SESSIONS`
 *  without repeating them by hand. */
function toIsoDate(label: string): string {
  const [monthName, day] = label.split(' ');
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  const month = months.indexOf(monthName) + 1;
  return `2026-${String(month).padStart(2, '0')}-${day.padStart(2, '0')}`;
}

// Every `HISTORY_SESSIONS` fixture row is `finished: true` with real
// numbers (see `history.fixture.ts`) -- the `!`s below just satisfy
// `HistorySession`'s nullable fields (issue #12's "In progress" rows),
// never actually hit on this fixture data.

export const SPEED_SERIES: readonly SumiLinePoint[] = HISTORY_SESSIONS.map((session) => ({
  date: toIsoDate(session.date),
  values: { speed: session.speedCharsPerMinute! },
}));

export const HELPS_SERIES: readonly SumiLinePoint[] = HISTORY_SESSIONS.map((session) => ({
  date: toIsoDate(session.date),
  values: { helps: session.helpsPerHundred! },
}));

export const SPEED_BY_STYLE: readonly SumiBar[] = [
  { label: 'Casual', value: 148 },
  { label: 'Polite', value: 139 },
  { label: 'Formal', value: 127 },
];

export const SPEED_BY_TOPIC: readonly SumiBar[] = [
  { label: 'Culture', value: 141 },
  { label: 'Current events', value: 143 },
  { label: 'Daily life', value: 135 },
  { label: 'History', value: 121 },
  { label: 'Science', value: 140 },
  { label: 'Short story', value: 146 },
  { label: 'Travel', value: 137 },
];

const totalCorrect = HISTORY_SESSIONS.reduce((sum, s) => sum + s.scoreCorrect!, 0);
const totalQuestions = HISTORY_SESSIONS.reduce((sum, s) => sum + s.scoreTotal!, 0);
const latest = HISTORY_SESSIONS[HISTORY_SESSIONS.length - 1];
const monthAgo = HISTORY_SESSIONS[3];

export const STATS_SUMMARY: StatsSummary = {
  speedCharsPerMinute: latest.speedCharsPerMinute!,
  speedDeltaPercent: Math.round(
    ((latest.speedCharsPerMinute! - monthAgo.speedCharsPerMinute!) /
      monthAgo.speedCharsPerMinute!) *
      100,
  ),
  helpsPerHundred: latest.helpsPerHundred!,
  comprehensionPercent: Math.round((totalCorrect / totalQuestions) * 100),
  readingLevel: 'N4',
  readingLevelDetail: 'comfortable · N3 with help',
};

export const PROBLEM_WORDS: readonly ProblemWord[] = [
  { word: '伺う', reading: 'うかがう', meaning: 'to visit / to ask (humble)', timesLookedUp: 4 },
  { word: '兼六園', reading: 'けんろくえん', meaning: 'Kenrokuen (garden)', timesLookedUp: 3 },
  { word: '概要', reading: 'がいよう', meaning: 'outline / summary', timesLookedUp: 3 },
  {
    word: '承知しました',
    reading: 'しょうちしました',
    meaning: 'understood (polite)',
    timesLookedUp: 2,
  },
  { word: '治部煮', reading: 'じぶに', meaning: 'jibuni (a Kanazawa dish)', timesLookedUp: 2 },
];
