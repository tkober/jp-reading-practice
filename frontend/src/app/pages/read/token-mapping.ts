import type { SumiReadingParagraph, SumiReadingWord } from 'sumi-ui/practice';
import type { ApiParagraph, ApiToken } from '../../core/api.types';

/**
 * Maps the backend's full per-word analysis (`ApiToken`, `backend/app/
 * models.py`'s `Token`) down to `sumi-reading-text`'s own lean shape
 * (`SumiReadingWord`: `{ id, text, reading?, unknown?, plain? }`) -- issue #9's one
 * pure, unit-tested bridge between the two, per the brief.
 *
 * The rules (brief):
 * - A token with no kanji at all has nothing worth a ruby reading over
 *   itself (a kana word's reading *is* its surface) -- `reading` stays
 *   `undefined` regardless of anything else.
 * - `needs_furigana` (unknown kanji, or a reading that does not compose
 *   from known kanji -- see `analysis.py`) -> always-visible ruby:
 *   `reading` set, `unknown: true`.
 * - A kanji word that does *not* need furigana (known, or every kanji
 *   composes) -> peekable ruby: `reading` set, `unknown` left `false`.
 * - A word whose `segments` split it into kanji and kana runs passes them
 *   on, so the ruby sits over each kanji run only, not over okurigana.
 * - `is_word === false` (particles, auxiliaries, punctuation) -> `plain`:
 *   ordinary running text, not focusable or tappable, never peeked
 *   (sumi-ui#112).
 *
 * Returns the full token lookup (`tokensById`) alongside the rendered
 * shape so the caller can resolve a tapped or peeked word back to its
 * token -- see `ReadSessionPage`.
 */
export interface MappedReadingText {
  paragraphs: readonly SumiReadingParagraph[];
  tokensById: ReadonlyMap<string, ApiToken>;
}

export function mapApiParagraphsToReadingText(
  paragraphs: readonly ApiParagraph[],
): MappedReadingText {
  const tokensById = new Map<string, ApiToken>();
  const mapped: SumiReadingParagraph[] = paragraphs.map((paragraph) =>
    paragraph.tokens.map((token) => {
      tokensById.set(token.id, token);
      return mapToken(token);
    }),
  );
  return { paragraphs: mapped, tokensById };
}

function mapToken(token: ApiToken): SumiReadingWord {
  const word: SumiReadingWord = { id: token.id, text: token.surface };
  if (!token.is_word) {
    word.plain = true;
  }
  if (token.kanji.length === 0) {
    return word;
  }
  word.reading = token.reading;
  // Ruby over the kanji runs only (飲/の + み), never over the okurigana.
  // A single segment is the whole word, which `reading` already covers.
  if (token.segments.length > 1) {
    word.segments = token.segments.map((segment) =>
      segment.reading ? { base: segment.base, reading: segment.reading } : { base: segment.base },
    );
  }
  if (token.needs_furigana) {
    word.unknown = true;
  }
  return word;
}
