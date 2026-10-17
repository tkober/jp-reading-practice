export interface StatsSummary {
  speedCharsPerMinute: number;
  /** Signed percent change over the last 30 days; `null` hides the delta. */
  speedDeltaPercent: number | null;
  helpsPerHundred: number;
  comprehensionPercent: number;
  /** e.g. "N4 comfortable · N3 with help". */
  readingLevel: string;
}

export interface ProblemWord {
  word: string;
  reading: string;
  meaning: string;
  timesLookedUp: number;
}
