// `sumi-reading-text` (sumi-ui#94, `sumi-ui/practice`) now owns the
// paragraph/word/activation shapes this screen used to define itself in
// `proto/tappable-ruby-text` -- re-exported here under their original
// (unprefixed) names so the rest of this feature does not have to spell
// out `Sumi...` everywhere a plain reading word is passed around.
export type {
  SumiReadingParagraph as ReadingParagraph,
  SumiReadingWord as ReadingWord,
  SumiReadingWordActivateEvent as WordActivateEvent,
  SumiReadingRange as ReadingRange,
  SumiReadingRangeSelectEvent as RangeSelectEvent,
} from 'sumi-ui/practice';

import type { SumiReadingParagraph } from 'sumi-ui/practice';

/** "Source: <title> ↗" (issue #15), resolved from the backend's own
 *  `TextSourceApi` by `pages/read/source-line.ts`'s pure `sourceLineFor` --
 *  shown under the reading screen's last paragraph and again on the
 *  summary (`SummaryScreen`'s own `source` input reuses this same shape). */
export interface SourceLine {
  label: string;
  link: string;
}

export interface ReadingTextData {
  titleJapanese: string;
  paragraphs: readonly SumiReadingParagraph[];
  /** `null`/absent for a text with no material source at all. */
  source?: SourceLine | null;
}

// The word lookup's own domain shapes. `sumi-popover` (sumi-ui#95) only
// supplies the anchored overlay shell -- title/header slot, body, actions
// slot, placement and focus handling -- it has no notion of a "word" at
// all, so what used to be `proto/word-popover-sheet`'s own types stay
// app-owned, projected into the popover's content from `reading-screen`.
export type WordActionKind =
  'explain' | 'translate' | 'grammar' | 'tutor' | 'translate_part' | 'grammar_part';

export interface WordActionOption {
  kind: WordActionKind;
  label: string;
  /** Help weight shown as a small hint, e.g. "2" -- see the concept's help weights. */
  weight: number;
}

export interface WordDetails {
  word: string;
  /** Omitted (or equal to `word`) for a kana-only word, where repeating it
   *  as a separate reading line would say nothing new. */
  reading?: string;
  jlptLevel?: string;
  meanings: readonly string[];
  /** e.g. "Kanji Trainer: Guru II" or "Not in Kanji Trainer" -- only shown
   *  for `kind: 'word'` (the default); a grammar pattern has no Kanji
   *  Trainer status of its own. */
  knownStatus?: string;
  /** Omitted (or empty) for issue #9: the popover shows no action buttons
   *  at all until #10 (Explain/Translate/Grammar/Tutor) wires them up. */
  actions?: readonly WordActionOption[];
  /** Shown instead of the meanings list while it is empty, e.g.
   *  "Loading…"; defaults to "No dictionary entry." */
  note?: string;
  /** `'word'` (default) looks up a single word, with a JLPT badge and
   *  Kanji Trainer status; `'grammar'` looks up a grammar pattern instead
   *  -- shown with a "Grammar" badge and no Kanji Trainer line; `'range'`
   *  (jp-reading-practice#32) is a learner-dragged span of words -- no
   *  reading line, no badge, no dictionary/Kanji Trainer section at all,
   *  just the span itself (`word`) and its own actions (or, for a span
   *  that crosses a sentence boundary, `note` alone and no actions). */
  kind?: 'word' | 'grammar' | 'range';
}

export interface WordAnswer {
  kind: WordActionKind;
  text: string;
  /** `true` when `text` is an error message (no OpenAI key, an upstream
   *  failure -- issue #10) rather than the tutor's actual answer, shown in
   *  the answer block with error styling, never as a page-level error. */
  isError?: boolean;
}

// `sumi-side-panel` (sumi-ui#96, `sumi-ui/layout`) is likewise just the
// docked-panel/full-height-sheet shell; the chat message shape stays here.
export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  /** `true` for a failed question (no OpenAI key, an upstream failure --
   *  issue #11), shown as an inline error right under it rather than a
   *  page-level error -- `text` is the error's own sentence. The learner's
   *  question itself is kept (the backend stores it even on failure) and
   *  can simply be asked again, as a new question. */
  isError?: boolean;
}
