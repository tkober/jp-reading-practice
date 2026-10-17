import { Component, computed, input, output, signal } from '@angular/core';
import {
  SumiButtonDirective,
  SumiInputDirective,
  SumiSegmentedControl,
  SumiTextareaDirective,
  type SumiSegmentedOption,
} from 'sumi-ui/forms';
import { SumiBadge, SumiCard, SumiPage } from 'sumi-ui/layout';
import type { TopicDefaultStyle, TopicDraft } from './topics.types';

const STYLE_OPTIONS: SumiSegmentedOption<TopicDefaultStyle>[] = [
  { value: 'Casual', label: 'Casual' },
  { value: 'Polite', label: 'Polite' },
  { value: 'Formal', label: 'Formal' },
];

@Component({
  selector: 'app-topic-edit-screen',
  templateUrl: './topic-edit-screen.html',
  styleUrl: './topic-edit-screen.scss',
  imports: [
    SumiPage,
    SumiCard,
    SumiBadge,
    SumiInputDirective,
    SumiTextareaDirective,
    SumiSegmentedControl,
    SumiButtonDirective,
  ],
  host: { class: 'app-topic-edit-screen' },
})
export class TopicEditScreen {
  readonly draft = input.required<TopicDraft>();
  /** Only the "Current events" topic has RSS feeds. */
  readonly showRssFeeds = input(false);
  /** Shown only for a saved, non-built-in topic -- built-ins are reset, not deleted. */
  readonly canDelete = input(false);
  /** Whether a built-in topic has been edited -- shows "customized" instead of "built-in". */
  readonly isBuiltin = input(false);
  readonly isCustomized = input(false);

  readonly nameChange = output<string>();
  readonly glyphChange = output<string>();
  readonly styleChange = output<TopicDefaultStyle>();
  readonly promptChange = output<string>();
  readonly rssFeedAdd = output<string>();
  readonly rssFeedRemove = output<number>();
  readonly save = output<void>();
  readonly reset = output<void>();
  readonly delete = output<void>();
  /** "← All topics" -- back to the list. */
  readonly back = output<void>();

  protected readonly styleOptions = STYLE_OPTIONS;

  protected readonly pageTitle = computed(() => this.draft().name || 'New topic');

  /**
   * A click on "Delete" only arms it; a second click on "Confirm" actually
   * emits `delete`. Local, presentational state -- no API call happens
   * here, same as jp-conversation-practice's scenario list, just inline on
   * the one button instead of a per-row confirm (there is only one topic
   * being edited at a time here).
   */
  protected readonly confirmingDelete = signal(false);

  protected onAddFeed(input: HTMLInputElement): void {
    const value = input.value.trim();
    if (!value) {
      return;
    }
    this.rssFeedAdd.emit(value);
    input.value = '';
  }

  protected requestDelete(): void {
    this.confirmingDelete.set(true);
  }

  protected cancelDelete(): void {
    this.confirmingDelete.set(false);
  }

  protected confirmDelete(): void {
    this.confirmingDelete.set(false);
    this.delete.emit();
  }
}
