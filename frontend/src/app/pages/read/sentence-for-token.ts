import type { ApiParagraph, ApiToken } from '../../core/api.types';

// A client-side mirror of the backend's `app/sentences.py`
// (`split_sentences`/`find_sentence`) -- used only to show the tutor
// chat's "About: ..." focus chip immediately on tap, before any round
// trip to the server. The backend computes its own `focus_sentence_key`
// independently from the same `focus_token_id` it is sent, so a mismatch
// here (there should not be one -- the rule is copied verbatim) would only
// ever affect this chip's own display text, never counting.
const SENTENCE_ENDERS = '。！？!?';
const CLOSING_BRACKETS = '」』）';

function isOnly(surface: string, chars: string): boolean {
  return surface.length > 0 && Array.from(surface).every((char) => chars.includes(char));
}

interface SentenceSpan {
  text: string;
  tokenIds: readonly string[];
}

function splitSentences(tokens: readonly ApiToken[]): SentenceSpan[] {
  const sentences: SentenceSpan[] = [];
  let currentIds: string[] = [];
  let currentText: string[] = [];

  const flush = (): void => {
    if (currentIds.length === 0) {
      return;
    }
    sentences.push({ text: currentText.join(''), tokenIds: currentIds });
    currentIds = [];
    currentText = [];
  };

  let index = 0;
  while (index < tokens.length) {
    const token = tokens[index];
    currentIds.push(token.id);
    currentText.push(token.surface);
    const ended = isOnly(token.surface, SENTENCE_ENDERS);
    index++;
    if (ended) {
      const next = tokens[index];
      if (next && isOnly(next.surface, CLOSING_BRACKETS)) {
        currentIds.push(next.id);
        currentText.push(next.surface);
        index++;
      }
      flush();
    }
  }
  flush(); // the trailing, partial sentence, if the paragraph has one

  return sentences;
}

/**
 * The sentence containing `tokenId`, as plain joined surface text -- or
 * `null` if `tokenId` is not found. `tokenId`'s own `"<paragraphIndex>-<n>"`
 * shape (`Token.id`, backend's `analysis.py`) names which paragraph to
 * split without scanning every one of them.
 */
export function sentenceForToken(
  paragraphs: readonly ApiParagraph[],
  tokenId: string,
): string | null {
  const paragraphIndex = Number(tokenId.split('-')[0]);
  const tokens = paragraphs[paragraphIndex]?.tokens;
  if (!tokens) {
    return null;
  }
  const sentence = splitSentences(tokens).find((span) => span.tokenIds.includes(tokenId));
  return sentence?.text ?? null;
}

/**
 * The sentence's own text if `startId` and `endId` (a range-selected
 * span's two ends, jp-reading-practice#32) both land in the *same*
 * sentence, `null` otherwise (including either id not found at all) --
 * `ReadingScreen`'s own client-side check, before it even opens the span
 * popover, so a cross-sentence drag shows "Select within one sentence."
 * immediately rather than waiting on a round trip that `/assist` would
 * reject anyway. Same rule as the backend's own `sentences.resolve_span`,
 * copied verbatim (see that module's own docstring on why a mismatch here
 * could only ever affect this early UI check, never counting).
 */
export function sameSentenceSpan(
  paragraphs: readonly ApiParagraph[],
  startId: string,
  endId: string,
): string | null {
  const paragraphIndex = Number(startId.split('-')[0]);
  if (paragraphIndex !== Number(endId.split('-')[0])) {
    return null; // different paragraphs -- never the same sentence
  }
  const tokens = paragraphs[paragraphIndex]?.tokens;
  if (!tokens) {
    return null;
  }
  const sentence = splitSentences(tokens).find((span) => span.tokenIds.includes(startId));
  if (!sentence || !sentence.tokenIds.includes(endId)) {
    return null;
  }
  return sentence.text;
}

/**
 * The chat focus chip's own display text, e.g. `"水を飲みます…"` for a long
 * sentence -- truncated at `maxLength` characters (Japanese has no spaces
 * to break on, so a hard cut plus an ellipsis is the only sane option).
 */
export function truncateForChip(text: string, maxLength = 40): string {
  const characters = Array.from(text);
  if (characters.length <= maxLength) {
    return text;
  }
  return `${characters.slice(0, maxLength).join('')}…`;
}
