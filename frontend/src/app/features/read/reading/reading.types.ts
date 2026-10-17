// `sumi-reading-text` (sumi-ui#94, `sumi-ui/practice`) now owns the
// paragraph/word/activation shapes this screen used to define itself in
// `proto/tappable-ruby-text` -- re-exported here under their original
// (unprefixed) names so the rest of this feature does not have to spell
// out `Sumi...` everywhere a plain reading word is passed around.
export type {
  SumiReadingParagraph as ReadingParagraph,
  SumiReadingWord as ReadingWord,
  SumiReadingWordActivateEvent as WordActivateEvent,
} from 'sumi-ui/practice';

import type { SumiReadingParagraph } from 'sumi-ui/practice';

export interface ReadingTextData {
  titleJapanese: string;
  paragraphs: readonly SumiReadingParagraph[];
}

// The word lookup's own domain shapes. `sumi-popover` (sumi-ui#95) only
// supplies the anchored overlay shell -- title/header slot, body, actions
// slot, placement and focus handling -- it has no notion of a "word" at
// all, so what used to be `proto/word-popover-sheet`'s own types stay
// app-owned, projected into the popover's content from `reading-screen`.
export type WordActionKind = 'explain' | 'translate' | 'grammar' | 'tutor';

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
   *  -- shown with a "Grammar" badge and no Kanji Trainer line. */
  kind?: 'word' | 'grammar';
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
}
