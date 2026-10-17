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
  /** Only meaningful for the "Current events" topic — see `showRssFeeds`. */
  rssFeeds: readonly string[];
}
