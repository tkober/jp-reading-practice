import { describe, expect, it } from 'vitest';
import type { ApiParagraph, ApiToken } from '../../core/api.types';
import { mapApiParagraphsToReadingText } from './token-mapping';

function token(overrides: Partial<ApiToken>): ApiToken {
  return {
    id: 't0',
    surface: 'surface',
    lemma: 'surface',
    reading: 'surface',
    lemma_reading: 'surface',
    pos: '名詞',
    segments: [],
    jlpt: null,
    kanji: [],
    known_word: false,
    needs_furigana: false,
    is_word: true,
    ...overrides,
  };
}

function paragraph(tokens: ApiToken[]): ApiParagraph {
  return { tokens };
}

describe('mapApiParagraphsToReadingText', () => {
  it('leaves a kana-only word with no reading at all -- there is nothing to peek', () => {
    const t = token({
      id: 'a',
      surface: 'あまり',
      reading: 'あまり',
      kanji: [],
      needs_furigana: false,
    });
    const { paragraphs } = mapApiParagraphsToReadingText([paragraph([t])]);
    expect(paragraphs[0][0]).toEqual({ id: 'a', text: 'あまり' });
  });

  it('shows an unknown kanji word as always-visible ruby (needs_furigana)', () => {
    const t = token({
      id: 'b',
      surface: '兼六園',
      reading: 'けんろくえん',
      kanji: [{ character: '兼', jlpt: null, known: false }],
      needs_furigana: true,
    });
    const { paragraphs } = mapApiParagraphsToReadingText([paragraph([t])]);
    expect(paragraphs[0][0]).toEqual({
      id: 'b',
      text: '兼六園',
      reading: 'けんろくえん',
      unknown: true,
    });
  });

  it('shows a known kanji word as peekable ruby (reading set, unknown falsy)', () => {
    const t = token({
      id: 'c',
      surface: '先週',
      reading: 'せんしゅう',
      kanji: [{ character: '先', jlpt: 5, known: true }],
      needs_furigana: false,
      known_word: true,
    });
    const { paragraphs } = mapApiParagraphsToReadingText([paragraph([t])]);
    const word = paragraphs[0][0];
    expect(word.text).toBe('先週');
    expect(word.reading).toBe('せんしゅう');
    expect(word.unknown).toBeFalsy();
  });

  it('keeps every token id reachable via tokensById, including non-word ones', () => {
    const particle = token({ id: 'p', surface: 'を', reading: 'を', is_word: false, kanji: [] });
    const word = token({
      id: 'w',
      surface: '猫',
      reading: 'ねこ',
      kanji: [{ character: '猫', jlpt: 5, known: true }],
    });
    const { tokensById } = mapApiParagraphsToReadingText([paragraph([word, particle])]);

    expect(tokensById.get('p')?.is_word).toBe(false);
    expect(tokensById.get('w')?.is_word).toBe(true);
    expect(tokensById.size).toBe(2);
  });

  it('maps multiple paragraphs, each to its own flat word array', () => {
    const a = token({ id: 'a', surface: 'あ' });
    const b = token({ id: 'b', surface: 'い' });
    const { paragraphs } = mapApiParagraphsToReadingText([paragraph([a]), paragraph([b])]);
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveLength(1);
    expect(paragraphs[1][0].id).toBe('b');
  });
});
