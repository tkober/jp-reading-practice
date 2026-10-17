export interface StatsSummary {
  speedCharsPerMinute: number;
  /** Signed percent change over the last 30 days; `null` hides the delta. */
  speedDeltaPercent: number | null;
  helpsPerHundred: number;
  comprehensionPercent: number;
  /** e.g. "N4" — short enough for `sumi-stat-tile`'s big tabular-figures
   *  value; the fuller description goes in `readingLevelDetail` instead,
   *  which the tile shows as its small muted `hint` line. */
  readingLevel: string;
  /** e.g. "comfortable · N3 with help". */
  readingLevelDetail: string;
}

export interface ProblemWord {
  word: string;
  reading: string;
  meaning: string;
  timesLookedUp: number;
}
