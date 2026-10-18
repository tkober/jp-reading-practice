export interface HistorySession {
  id: string;
  date: string;
  titleJapanese: string;
  topicName: string;
  length: 'Short' | 'Medium' | 'Long';
  /** `false` for a session still in `reading`/`questions` -- the four
   *  numbers below are then all `null` and the row shows "In progress"
   *  instead of them. */
  finished: boolean;
  speedCharsPerMinute: number | null;
  helpsPerHundred: number | null;
  scoreCorrect: number | null;
  scoreTotal: number | null;
}
