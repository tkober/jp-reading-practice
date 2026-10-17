import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ReadingScreen } from '../../features/read/reading/reading-screen';
import type {
  ChatMessage,
  WordActionKind,
  WordActionOption,
  WordAnchorRect,
  WordAnswer,
  WordDetails,
} from '../../features/read/reading/reading.types';
import type { WordActivateEvent } from '../../proto/tappable-ruby-text/tappable-ruby-text';
import { READING_TEXT } from '../fixtures/reading-text.fixture';
import { CHAT_MESSAGES, WORD_ANSWER_GRAMMAR, WORD_DETAILS_KOTO } from '../fixtures/word-lookup.fixture';

export type ReadingPreviewVariant = 'default' | 'word' | 'answer' | 'chat' | 'furigana-all' | 'paused';

const DEFAULT_ACTIONS: readonly WordActionOption[] = [
  { kind: 'explain', label: 'Explain word', weight: 2 },
  { kind: 'translate', label: 'Translate sentence', weight: 3 },
  { kind: 'grammar', label: 'Explain grammar', weight: 3 },
  { kind: 'tutor', label: 'Ask tutor', weight: 3 },
];

const FIXED_ANCHOR: WordAnchorRect = { x: 420, y: 260, width: 64, height: 32 };

/** One component behind six `/preview/reading*` routes — see
 *  `SetupPreview`'s doc comment for why. */
@Component({
  selector: 'preview-reading',
  template: `
    <app-reading-screen
      [text]="text"
      [elapsedLabel]="elapsedLabel()"
      [paused]="paused()"
      [furiganaEverywhere]="furiganaEverywhere()"
      [selectedWord]="selectedWord()"
      [selectedWordAnchor]="selectedWordAnchor()"
      [selectedWordId]="selectedWordId()"
      [wordAnswer]="wordAnswer()"
      [chatOpen]="chatOpen()"
      [chatMessages]="chatMessages()"
      [chatSending]="chatSending()"
      (wordActivate)="onWordActivate($event)"
      (closeWord)="onCloseWord()"
      (wordAction)="onWordAction($event)"
      (pauseToggle)="paused.set(!paused())"
      (chatToggle)="chatOpen.set(!chatOpen())"
      (chatSend)="onChatSend($event)"
      (doneReading)="doneReading.set(true)"
    />
    @if (doneReading()) {
      <p class="preview-note">→ would navigate to /preview/questions</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [ReadingScreen],
})
export class ReadingPreview {
  protected readonly text = READING_TEXT;
  protected readonly elapsedLabel = signal('3:12');
  protected readonly paused = signal(false);
  protected readonly furiganaEverywhere = signal(false);

  protected readonly selectedWord = signal<WordDetails | null>(null);
  protected readonly selectedWordAnchor = signal<WordAnchorRect | null>(null);
  protected readonly selectedWordId = signal<string | null>(null);
  protected readonly wordAnswer = signal<WordAnswer | null>(null);

  protected readonly chatOpen = signal(false);
  protected readonly chatMessages = signal<readonly ChatMessage[]>(CHAT_MESSAGES.slice(0, 2));
  protected readonly chatSending = signal(false);

  protected readonly doneReading = signal(false);

  constructor() {
    const variant = (inject(ActivatedRoute).snapshot.data['variant'] ?? 'default') as ReadingPreviewVariant;
    if (variant === 'word') {
      this.selectedWord.set(WORD_DETAILS_KOTO);
      this.selectedWordAnchor.set(FIXED_ANCHOR);
    } else if (variant === 'answer') {
      this.selectedWord.set(WORD_DETAILS_KOTO);
      this.selectedWordAnchor.set(FIXED_ANCHOR);
      this.wordAnswer.set(WORD_ANSWER_GRAMMAR);
    } else if (variant === 'chat') {
      this.chatOpen.set(true);
      this.chatMessages.set(CHAT_MESSAGES);
    } else if (variant === 'furigana-all') {
      this.furiganaEverywhere.set(true);
    } else if (variant === 'paused') {
      this.paused.set(true);
    }
  }

  protected onWordActivate(event: WordActivateEvent): void {
    const word = event.word;
    this.selectedWordId.set(word.id);
    this.selectedWordAnchor.set({
      x: event.rect.x,
      y: event.rect.y,
      width: event.rect.width,
      height: event.rect.height,
    });
    this.selectedWord.set({
      word: word.text,
      reading: word.reading ?? word.text,
      meanings: ['(preview placeholder — real lookup data arrives with #10+)'],
      knownStatus: word.unknown ? 'Not in Kanji Trainer' : 'Kanji Trainer: Guru II',
      actions: DEFAULT_ACTIONS,
    });
    this.wordAnswer.set(null);
  }

  protected onCloseWord(): void {
    this.selectedWord.set(null);
    this.selectedWordAnchor.set(null);
    this.selectedWordId.set(null);
    this.wordAnswer.set(null);
  }

  protected onWordAction(kind: WordActionKind): void {
    this.wordAnswer.set({ kind, text: `(preview placeholder ${kind} answer — real text arrives with #10+)` });
  }

  protected onChatSend(message: string): void {
    this.chatMessages.update((messages) => [...messages, { role: 'user', text: message }]);
    this.chatSending.set(true);
    setTimeout(() => {
      this.chatMessages.update((messages) => [
        ...messages,
        { role: 'assistant', text: '(preview placeholder reply — real answers arrive with #10+)' },
      ]);
      this.chatSending.set(false);
    }, 600);
  }
}
