// Preview-only fixture data — not the learner's own data.
import type { SumiTileOption } from 'sumi-ui/forms';
import type { TopicDraft, TopicSummary } from '../../features/topics/topics.types';
import type { JlptShares } from '../../features/read/setup/setup.types';

// Includes the "Surprise me" tile (`special: true`) as a normal option —
// `sumi-tile-picker` (sumi-ui#98) has no dedicated slot for it, see
// `SetupScreen.topics`'s doc comment.
export const TOPIC_TILES: readonly SumiTileOption<string>[] = [
  { value: 'daily-life', glyph: '日常', label: 'Daily life', lang: 'ja' },
  { value: 'history', glyph: '歴史', label: 'History', lang: 'ja' },
  { value: 'current-events', glyph: 'ニュース', label: 'Current events', lang: 'ja' },
  { value: 'culture', glyph: '文化', label: 'Culture', lang: 'ja' },
  { value: 'travel', glyph: '旅行', label: 'Travel', lang: 'ja' },
  { value: 'science', glyph: '科学', label: 'Science', lang: 'ja' },
  { value: 'short-story', glyph: '物語', label: 'Short story', lang: 'ja' },
  { value: 'surprise', glyph: '✨', label: 'Surprise me', special: true },
];

export const TOPIC_SUMMARIES: readonly TopicSummary[] = [
  { id: 'daily-life', glyph: '日常', name: 'Daily life', defaultStyle: 'Casual', customized: false },
  { id: 'history', glyph: '歴史', name: 'History', defaultStyle: 'Formal', customized: false },
  {
    id: 'current-events',
    glyph: 'ニュース',
    name: 'Current events',
    defaultStyle: 'Formal',
    customized: true,
  },
  { id: 'culture', glyph: '文化', name: 'Culture', defaultStyle: 'Polite', customized: false },
  { id: 'travel', glyph: '旅行', name: 'Travel', defaultStyle: 'Polite', customized: true },
  { id: 'science', glyph: '科学', name: 'Science', defaultStyle: 'Formal', customized: false },
  { id: 'short-story', glyph: '物語', name: 'Short story', defaultStyle: 'Casual', customized: false },
];

export const TOPIC_DRAFT_CURRENT_EVENTS: TopicDraft = {
  id: 'current-events',
  name: 'Current events',
  glyph: 'ニュース',
  defaultStyle: 'Formal',
  prompt:
    'Write a short news-style text summarising a recent, everyday topic — nothing political or ' +
    'graphic. Keep the tone neutral and factual, like a national broadcaster.',
  rssFeeds: ['https://www3.nhk.or.jp/rss/news/cat0.xml'],
};

export const DEFAULT_JLPT_MIX: JlptShares = { n5: 50, n4: 35, n3: 15, n2: 0, n1: 0 };
