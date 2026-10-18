export interface LookedUpWord {
  word: string;
  reading: string;
  meaning: string;
}

/** Same "Source: <title> ↗" shape the reading screen shows (issue #15) --
 *  re-exported here so the summary screen does not need to reach into the
 *  reading feature's own types for this one shape. */
export type { SourceLine } from '../reading/reading.types';
