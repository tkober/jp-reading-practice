export type TopicDefaultStyle = 'Casual' | 'Polite' | 'Formal';

export interface TopicSummary {
  id: string;
  glyph: string;
  name: string;
  defaultStyle: TopicDefaultStyle;
  /** `false` shows a "built-in" badge, `true` a "customized" one. */
  customized: boolean;
}

export interface TopicDraft {
  /** `null` for a new topic that has not been saved yet. */
  id: string | null;
  name: string;
  glyph: string;
  defaultStyle: TopicDefaultStyle;
  prompt: string;
  /** A topic becomes "news-backed" for generation simply by having at
   *  least one of these (issue #15) -- any topic can. */
  rssFeeds: readonly string[];
}
