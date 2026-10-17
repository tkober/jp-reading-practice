import { Component, signal } from '@angular/core';
import { TopicEditScreen } from '../../features/topics/topic-edit-screen';
import type { TopicDraft } from '../../features/topics/topics.types';
import { TOPIC_DRAFT_CURRENT_EVENTS } from '../fixtures/topics.fixture';

@Component({
  selector: 'preview-topic-edit',
  template: `
    <app-topic-edit-screen
      [draft]="draft()"
      [showRssFeeds]="true"
      (nameChange)="draft.update((d) => ({ ...d, name: $event }))"
      (glyphChange)="draft.update((d) => ({ ...d, glyph: $event }))"
      (styleChange)="draft.update((d) => ({ ...d, defaultStyle: $event }))"
      (promptChange)="draft.update((d) => ({ ...d, prompt: $event }))"
      (rssFeedAdd)="onFeedAdd($event)"
      (rssFeedRemove)="onFeedRemove($event)"
      (save)="saved.set(true)"
      (reset)="draft.set(initial)"
    />
    @if (saved()) {
      <p class="preview-note">→ saved (preview only)</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [TopicEditScreen],
})
export class TopicEditPreview {
  protected readonly initial: TopicDraft = TOPIC_DRAFT_CURRENT_EVENTS;
  protected readonly draft = signal<TopicDraft>(this.initial);
  protected readonly saved = signal(false);

  protected onFeedAdd(feed: string): void {
    this.draft.update((d) => ({ ...d, rssFeeds: [...d.rssFeeds, feed] }));
  }

  protected onFeedRemove(index: number): void {
    this.draft.update((d) => ({ ...d, rssFeeds: d.rssFeeds.filter((_, i) => i !== index) }));
  }
}
