import { Component, signal } from '@angular/core';
import { TopicsListScreen } from '../../features/topics/topics-list-screen';
import { TOPIC_SUMMARIES } from '../fixtures/topics.fixture';

@Component({
  selector: 'preview-topics',
  template: `
    <app-topics-list-screen
      [topics]="topics"
      (newTopic)="action.set('new topic')"
      (editTopic)="action.set('edit ' + $event)"
    />
    @if (action(); as a) {
      <p class="preview-note">→ would open the topic editor ({{ a }})</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [TopicsListScreen],
})
export class TopicsPreview {
  protected readonly topics = TOPIC_SUMMARIES;
  protected readonly action = signal<string | null>(null);
}
