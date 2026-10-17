import type { SumiReadingParagraph } from 'sumi-ui/practice';
import type { ApiParagraph, ApiToken } from '../../core/api.types';

/**
 * Maps the backend's full per-word analysis (`ApiToken`, `backend/app/
 * models.py`'s `Token`) down to `sumi-reading-text`'s own lean shape
 * (`SumiReadingWord`: `{ id, text, reading?, unknown? }`) -- issue #9's one
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
 * - `is_word === false` (particles, auxiliaries, punctuation) is NOT
 *   expressed here at all -- `sumi-reading-text` has no notion of a
 *   non-tappable word (every span is a button), so "not tappable" is an
 *   app-level decision made from `tokensById` at the point a tap is
 *   handled (`wordActivate`), not something this mapping can encode.
 *
 * Returns the full token lookup (`tokensById`) alongside the rendered
 * shape precisely so the caller can make that decision, and others like
 * it (e.g. "is this token even a dictionary word to look up") -- see
 * `ReadSessionPage`.
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

function mapToken(token: ApiToken): {
  id: string;
  text: string;
  reading?: string;
  unknown?: boolean;
} {
  const hasKanji = token.kanji.length > 0;
  if (!hasKanji) {
    return { id: token.id, text: token.surface };
  }
  if (token.needs_furigana) {
    return { id: token.id, text: token.surface, reading: token.reading, unknown: true };
  }
  return { id: token.id, text: token.surface, reading: token.reading };
}
