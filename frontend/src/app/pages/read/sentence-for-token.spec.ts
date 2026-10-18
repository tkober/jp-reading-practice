import { describe, expect, it } from 'vitest';
import type { ApiParagraph, ApiToken } from '../../core/api.types';
import { sameSentenceSpan, sentenceForToken, truncateForChip } from './sentence-for-token';

function token(id: string, surface: string): ApiToken {
  return {
    id,
    surface,
    lemma: surface,
    reading: surface,
    lemma_reading: surface,
    pos: '名詞',
    segments: [],
    jlpt: null,
    kanji: [],
    known_word: false,
    needs_furigana: false,
    is_word: true,
  };
}

function paragraph(surfaces: readonly string[], paragraphIndex = 0): ApiParagraph {
  return { tokens: surfaces.map((surface, i) => token(`${paragraphIndex}-${i}`, surface)) };
}

describe('sentenceForToken', () => {
  it('returns the sentence containing the token, joined from its surfaces', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。', '猫', 'が', 'いる', '。'])];
    expect(sentenceForToken(paragraphs, '0-2')).toBe('水を飲む。'); // 飲む
    expect(sentenceForToken(paragraphs, '0-6')).toBe('猫がいる。'); // いる
  });

  it('includes a trailing partial sentence with no final ender', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。', 'まだ', '書いている'])];
    expect(sentenceForToken(paragraphs, '0-5')).toBe('まだ書いている');
  });

  it('keeps a closing quote directly after the ender in the same sentence', () => {
    // 「そうだ。」と言った。
    const paragraphs = [paragraph(['「', 'そうだ', '。', '」', 'と', '言った', '。'])];
    expect(sentenceForToken(paragraphs, '0-1')).toBe('「そうだ。」');
    expect(sentenceForToken(paragraphs, '0-5')).toBe('と言った。');
  });

  it('resolves the paragraph from the token id, for a second paragraph', () => {
    const paragraphs = [paragraph(['あ', '。'], 0), paragraph(['い', '。'], 1)];
    expect(sentenceForToken(paragraphs, '1-0')).toBe('い。');
  });

  it('returns null for an unknown token id', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。'])];
    expect(sentenceForToken(paragraphs, '0-99')).toBeNull();
    expect(sentenceForToken(paragraphs, '5-0')).toBeNull();
  });
});

describe('sameSentenceSpan (jp-reading-practice#32)', () => {
  it('returns the sentence text when both ids land in the same sentence', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。', '猫', 'が', 'いる', '。'])];
    expect(sameSentenceSpan(paragraphs, '0-0', '0-2')).toBe('水を飲む。');
  });

  it('returns null when the two ids are in different sentences of the same paragraph', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。', '猫', 'が', 'いる', '。'])];
    expect(sameSentenceSpan(paragraphs, '0-0', '0-6')).toBeNull();
  });

  it('returns null when the two ids are in different paragraphs', () => {
    const paragraphs = [paragraph(['あ', '。'], 0), paragraph(['い', '。'], 1)];
    expect(sameSentenceSpan(paragraphs, '0-0', '1-0')).toBeNull();
  });

  it('returns null for an unknown id', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。'])];
    expect(sameSentenceSpan(paragraphs, '0-0', '0-99')).toBeNull();
  });

  it('works with the ids given in either order', () => {
    const paragraphs = [paragraph(['水', 'を', '飲む', '。'])];
    expect(sameSentenceSpan(paragraphs, '0-2', '0-0')).toBe('水を飲む。');
  });
});

describe('truncateForChip', () => {
  it('leaves a short sentence untouched', () => {
    expect(truncateForChip('水を飲みます。', 40)).toBe('水を飲みます。');
  });

  it('cuts a long sentence and adds an ellipsis', () => {
    const long = '猫'.repeat(50);
    const result = truncateForChip(long, 40);
    expect(result).toBe(`${'猫'.repeat(40)}…`);
    expect(Array.from(result)).toHaveLength(41);
  });
});
