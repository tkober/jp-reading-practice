import { Component, computed, inject, signal } from '@angular/core';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

import { Api } from '../../core/api';
import type { TopicApi, TopicCreatePayload, TopicStyleApi, TopicUpdatePayload } from '../../core/api.types';
import { isBackendUnreachable } from '../../core/unreachable';
import { TopicEditScreen } from '../../features/topics/topic-edit-screen';
import { TopicsListScreen } from '../../features/topics/topics-list-screen';
import type { TopicDefaultStyle, TopicDraft, TopicSummary } from '../../features/topics/topics.types';

type Mode = 'list' | 'edit';
type SaveState = 'idle' | 'saving' | 'saved' | 'error';

const STYLE_TO_API: Record<TopicDefaultStyle, TopicStyleApi> = {
  Casual: 'casual',
  Polite: 'polite',
  Formal: 'formal',
};
const STYLE_FROM_API: Record<TopicStyleApi, TopicDefaultStyle> = {
  casual: 'Casual',
  polite: 'Polite',
  formal: 'Formal',
};

const BLANK_DRAFT: TopicDraft = {
  id: null,
  name: '',
  glyph: '',
  defaultStyle: 'Casual',
  prompt: '',
  rssFeeds: [],
};

function toSummary(topic: TopicApi): TopicSummary {
  return {
    id: String(topic.id),
    glyph: topic.glyph,
    name: topic.title,
    defaultStyle: STYLE_FROM_API[topic.default_style],
    customized: topic.is_customized,
  };
}

function toDraft(topic: TopicApi): TopicDraft {
  return {
    id: String(topic.id),
    name: topic.title,
    glyph: topic.glyph,
    defaultStyle: STYLE_FROM_API[topic.default_style],
    prompt: topic.prompt,
    rssFeeds: topic.feed_urls,
  };
}

/**
 * Wires `features/topics/` (the approved design's list + editor) into the
 * real `/topics` route against `POST/GET/PUT/DELETE /api/topics` and the
 * `/reset` action -- issue #8. One route, two screens: `mode` switches
 * between them rather than a nested child route, since the editor has
 * nothing of its own worth deep-linking to yet.
 */
@Component({
  selector: 'app-topics',
  imports: [...SUMI_LAYOUT, TopicsListScreen, TopicEditScreen],
  templateUrl: './topics.html',
  styleUrl: './topics.scss',
})
export class TopicsPage {
  private readonly api = inject(Api);

  protected readonly mode = signal<Mode>('list');

  protected readonly topics = signal<TopicApi[]>([]);
  protected readonly loadError = signal<string | null>(null);
  /** The topic list itself could not be loaded at all -- T6, not a banner. */
  protected readonly failed = signal(false);

  /** The full row currently being edited, `null` for a not-yet-saved new topic. */
  private readonly editingTopic = signal<TopicApi | null>(null);
  protected readonly draft = signal<TopicDraft>(BLANK_DRAFT);

  protected readonly saveState = signal<SaveState>('idle');
  protected readonly saveMessage = signal<string | null>(null);
  protected readonly busy = signal(false);

  protected readonly summaries = computed(() => this.topics().map(toSummary));
  protected readonly isBuiltin = computed(() => this.editingTopic()?.is_builtin ?? false);
  protected readonly isCustomized = computed(() => this.editingTopic()?.is_customized ?? false);
  /** Only a saved, non-built-in topic can be deleted -- built-ins are reset instead. */
  protected readonly canDelete = computed(() => {
    const topic = this.editingTopic();
    return topic !== null && !topic.is_builtin;
  });
  /** Only the "Current events" topic shows the RSS feed editor (per the approved design). */
  protected readonly showRssFeeds = computed(() => this.editingTopic()?.slug === 'current-events');

  constructor() {
    this.reload();
  }

  reload(): void {
    this.api.topics().then(
      (topics) => {
        this.failed.set(false);
        this.topics.set(topics);
        this.loadError.set(null);
      },
      (error: unknown) => {
        if (isBackendUnreachable(error)) {
          this.failed.set(true);
        } else {
          this.loadError.set((error as Error).message);
        }
      },
    );
  }

  // --- navigation between the two screens -----------------------------------

  openNewTopic(): void {
    this.editingTopic.set(null);
    this.draft.set(BLANK_DRAFT);
    this.saveState.set('idle');
    this.saveMessage.set(null);
    this.mode.set('edit');
  }

  openTopic(id: string): void {
    const topic = this.topics().find((t) => String(t.id) === id);
    if (!topic) {
      return;
    }
    this.editingTopic.set(topic);
    this.draft.set(toDraft(topic));
    this.saveState.set('idle');
    this.saveMessage.set(null);
    this.mode.set('edit');
  }

  backToList(): void {
    this.mode.set('list');
    this.reload();
  }

  // --- draft edits ------------------------------------------------------------

  setName(name: string): void {
    this.draft.update((d) => ({ ...d, name }));
  }

  setGlyph(glyph: string): void {
    this.draft.update((d) => ({ ...d, glyph }));
  }

  setStyle(style: TopicDefaultStyle): void {
    this.draft.update((d) => ({ ...d, defaultStyle: style }));
  }

  setPrompt(prompt: string): void {
    this.draft.update((d) => ({ ...d, prompt }));
  }

  addFeed(url: string): void {
    this.draft.update((d) => ({ ...d, rssFeeds: [...d.rssFeeds, url] }));
  }

  removeFeed(index: number): void {
    this.draft.update((d) => ({ ...d, rssFeeds: d.rssFeeds.filter((_, i) => i !== index) }));
  }

  // --- save / reset / delete ---------------------------------------------------

  save(): void {
    if (this.busy()) {
      return;
    }
    const draft = this.draft();
    const payload = {
      title: draft.name.trim(),
      glyph: draft.glyph.trim(),
      prompt: draft.prompt.trim(),
      default_style: STYLE_TO_API[draft.defaultStyle],
      feed_urls: draft.rssFeeds,
    };

    this.busy.set(true);
    this.saveState.set('saving');

    const request: Promise<TopicApi> =
      draft.id === null
        ? this.api.createTopic(payload as TopicCreatePayload)
        : this.api.updateTopic(Number(draft.id), payload as TopicUpdatePayload);

    request.then(
      (topic) => {
        this.busy.set(false);
        this.editingTopic.set(topic);
        this.draft.set(toDraft(topic));
        this.saveState.set('saved');
        this.saveMessage.set('Saved.');
      },
      (error: unknown) => {
        this.busy.set(false);
        this.saveState.set('error');
        this.saveMessage.set((error as Error).message);
      },
    );
  }

  resetToBuiltin(): void {
    const topic = this.editingTopic();
    if (!topic || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.api.resetTopic(topic.id).then(
      (reset) => {
        this.busy.set(false);
        this.editingTopic.set(reset);
        this.draft.set(toDraft(reset));
        this.saveState.set('saved');
        this.saveMessage.set('Reset to the built-in version.');
      },
      (error: unknown) => {
        this.busy.set(false);
        this.saveState.set('error');
        this.saveMessage.set((error as Error).message);
      },
    );
  }

  /**
   * Called from the editor's `delete` output, which only fires after its
   * own in-page two-step confirmation ("Delete this topic?" -> Confirm) --
   * no confirmation here, that would be a second, redundant prompt.
   */
  deleteTopic(): void {
    const topic = this.editingTopic();
    if (!topic || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.api.deleteTopic(topic.id).then(
      () => {
        this.busy.set(false);
        this.backToList();
      },
      (error: unknown) => {
        this.busy.set(false);
        this.saveState.set('error');
        this.saveMessage.set((error as Error).message);
      },
    );
  }
}
