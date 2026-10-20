import { Component, afterNextRender, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import type { SumiReadingRange, SumiReadingRangeSelectEvent } from 'sumi-ui/practice';
import { ReadingScreen } from '../../features/read/reading/reading-screen';
import type {
  ChatMessage,
  ReadingWord,
  WordActionKind,
  WordActionOption,
  WordAnswer,
  WordDetails,
  WordActivateEvent,
} from '../../features/read/reading/reading.types';
import { READING_TEXT, findWordByText } from '../fixtures/reading-text.fixture';
import {
  CHAT_MESSAGES,
  GRAMMAR_ANCHOR_WORD,
  RANGE_ANCHOR_WORDS,
  WORD_ANSWER_GRAMMAR,
  WORD_ANSWER_RANGE,
  WORD_DETAILS_GRAMMAR,
  WORD_DETAILS_PRIMARY,
  WORD_DETAILS_RANGE,
} from '../fixtures/word-lookup.fixture';

export type ReadingPreviewVariant =
  | 'default'
  | 'word'
  | 'answer'
  | 'chat'
  | 'chat-focus'
  | 'peek'
  | 'paused'
  | 'range'
  | 'range-answer';

/** The chat focus chip's own fixture text (issue #11) -- the sentence
 *  "Ask tutor" would carry as the next question's focus. */
const CHAT_FOCUS_SENTENCE = '濡れても気にしないことにしました。';

const DEFAULT_ACTIONS: readonly WordActionOption[] = [
  { kind: 'explain', label: 'Explain word', weight: 2 },
  { kind: 'translate', label: 'Translate sentence', weight: 3 },
  { kind: 'grammar', label: 'Explain grammar', weight: 3 },
  { kind: 'tutor', label: 'Ask tutor', weight: 3 },
];

/** Finds the rendered word span for a word's exact surface text, the same
 *  way `sumi-reading-text`'s own words are told apart in the DOM (there is
 *  no `data-word-id`) — see the callers' doc comments for why this exists
 *  at all. */
function findWordSpan(text: string): HTMLElement | null {
  const spans = Array.from(document.querySelectorAll<HTMLElement>('[role="button"]'));
  return spans.find((span) => span.textContent?.trim().startsWith(text)) ?? null;
}

/** One component behind six `/preview/reading*` routes — see
 *  `SetupPreview`'s doc comment for why. */
@Component({
  selector: 'preview-reading',
  template: `
    <app-reading-screen
      [text]="text"
      [elapsedLabel]="elapsedLabel()"
      [paused]="paused()"
      [selectedWord]="selectedWord()"
      [selectedWordId]="selectedWordId()"
      [wordAnswer]="wordAnswer()"
      [selectedRange]="selectedRange()"
      [chatOpen]="chatOpen()"
      [chatMessages]="chatMessages()"
      [chatSending]="chatSending()"
      [chatFocus]="chatFocus()"
      (wordActivate)="onWordActivate($event)"
      (readingPeeked)="onReadingPeeked($event)"
      (rangeSelected)="onRangeSelected($event)"
      (closeWord)="onCloseWord()"
      (wordAction)="onWordAction($event)"
      (pauseToggle)="paused.set(!paused())"
      (chatToggle)="chatOpen.set(!chatOpen())"
      (chatSend)="onChatSend($event)"
      (chatFocusClear)="chatFocus.set(null)"
      (doneReading)="doneReading.set(true)"
    />
    @if (doneReading()) {
      <p class="preview-note">→ would navigate to /preview/questions</p>
    }
    @if (lastPeek(); as word) {
      <p class="preview-note">
        → readingPeeked: {{ word.text }} ({{ word.reading }}) — a weight-1 help, logged once per
        word
      </p>
    }
  `,
  styles: [
    '.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }',
  ],
  imports: [ReadingScreen],
})
export class ReadingPreview {
  protected readonly text = READING_TEXT;
  protected readonly elapsedLabel = signal('3:12');
  protected readonly paused = signal(false);
  protected readonly lastPeek = signal<ReadingWord | null>(null);

  protected readonly selectedWord = signal<WordDetails | null>(null);
  protected readonly selectedWordId = signal<string | null>(null);
  protected readonly wordAnswer = signal<WordAnswer | null>(null);
  protected readonly selectedRange = signal<SumiReadingRange | null>(null);

  protected readonly chatOpen = signal(false);
  protected readonly chatMessages = signal<readonly ChatMessage[]>(CHAT_MESSAGES.slice(0, 2));
  protected readonly chatSending = signal(false);
  protected readonly chatFocus = signal<string | null>(null);

  protected readonly doneReading = signal(false);

  constructor() {
    const variant = (inject(ActivatedRoute).snapshot.data['variant'] ??
      'default') as ReadingPreviewVariant;
    if (variant === 'chat') {
      this.chatOpen.set(true);
      this.chatMessages.set(CHAT_MESSAGES);
    } else if (variant === 'chat-focus') {
      // "Ask tutor" on a word, before the question is sent -- the chip
      // above the composer, with one prior exchange still showing behind
      // it (the focus is about the *next* question, not a reset of the
      // conversation already in progress).
      this.chatOpen.set(true);
      this.chatMessages.set(CHAT_MESSAGES.slice(0, 2));
      this.chatFocus.set(CHAT_FOCUS_SENTENCE);
    } else if (variant === 'paused') {
      this.paused.set(true);
    } else if (
      variant === 'word' ||
      variant === 'answer' ||
      variant === 'peek' ||
      variant === 'range' ||
      variant === 'range-answer'
    ) {
      // The popover anchors on the word element `wordActivated` carries,
      // and the hover/long-press peek has no preview-only override (the
      // old prototype's `forcePeekWordId` has no library equivalent).
      // Dispatching the *real* gesture on the rendered
      // word span after the first render exercises the exact same code
      // path a learner's tap/hover (or, for the two range variants, a
      // real mouse drag resolved by `sumi-reading-text` itself) would,
      // which is simpler than threading a second, preview-only bypass
      // through `ReadingScreen` for a state a real interaction can
      // already produce.
      afterNextRender(() => this.simulateVariant(variant));
    }
  }

  private simulateVariant(variant: 'word' | 'answer' | 'peek' | 'range' | 'range-answer'): void {
    if (variant === 'peek') {
      const span = findWordSpan('旅行');
      span?.dispatchEvent(
        new PointerEvent('pointerenter', { pointerType: 'mouse', bubbles: true }),
      );
      return;
    }

    if (variant === 'range' || variant === 'range-answer') {
      this.simulateRangeSelection();
      // `onRangeSelected` (below) already sets the real `WORD_DETAILS_RANGE`
      // fixture from the resolved event, so only the answer (for
      // `range-answer`) needs adding on top.
      if (variant === 'range-answer') {
        this.wordAnswer.set(WORD_ANSWER_RANGE);
      }
      return;
    }

    const targetWord = variant === 'word' ? findWordByText('濡れても') : GRAMMAR_ANCHOR_WORD;
    const span = findWordSpan(targetWord.text);
    span?.click();
    // `onWordActivate` (below) just set a generic placeholder from the
    // clicked word's own surface text/reading — replace it with this
    // variant's curated fixture content, same as the old preview did
    // before `selectedWordAnchor` existed to resolve from a real click.
    if (variant === 'word') {
      this.selectedWord.set(WORD_DETAILS_PRIMARY);
    } else {
      this.selectedWord.set(WORD_DETAILS_GRAMMAR);
      this.wordAnswer.set(WORD_ANSWER_GRAMMAR);
    }
  }

  /** Builds a real, non-collapsed `Selection` across `RANGE_ANCHOR_WORDS`'
   *  two word spans and fires the same `pointerup` a real mouse drag's
   *  release would -- `sumi-reading-text` resolves it exactly as it would
   *  a learner's own drag, through `onRangeSelected` below. */
  private simulateRangeSelection(): void {
    const [start, end] = RANGE_ANCHOR_WORDS;
    const startSpan = findWordSpan(start.text);
    const endSpan = findWordSpan(end.text);
    if (!startSpan || !endSpan) {
      return;
    }
    const range = document.createRange();
    range.setStart(startSpan, 0);
    range.setEnd(endSpan, endSpan.childNodes.length);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    endSpan.dispatchEvent(new PointerEvent('pointerup', { pointerType: 'mouse', bubbles: true }));
  }

  protected onWordActivate(event: WordActivateEvent): void {
    const word = event.word;
    this.selectedWordId.set(word.id);
    this.selectedWord.set({
      word: word.text,
      reading: word.reading ?? word.text,
      meanings: ['(preview placeholder — real lookup data arrives with #10+)'],
      knownStatus: word.unknown ? 'Not in Kanji Trainer' : 'Kanji Trainer: Guru II',
      actions: DEFAULT_ACTIONS,
    });
    this.wordAnswer.set(null);
    this.selectedRange.set(null);
  }

  protected onReadingPeeked(word: ReadingWord): void {
    this.lastPeek.set(word);
  }

  protected onRangeSelected(event: SumiReadingRangeSelectEvent): void {
    this.selectedRange.set({ startId: event.startId, endId: event.endId });
    this.selectedWordId.set(null);
    this.wordAnswer.set(null);
    // Same curated fixture regardless of which real span the simulated
    // drag (or, outside the 'range'/'range-answer' variants, a genuine
    // preview-page drag) actually resolved to.
    this.selectedWord.set(WORD_DETAILS_RANGE);
  }

  protected onCloseWord(): void {
    this.selectedWord.set(null);
    this.selectedWordId.set(null);
    this.wordAnswer.set(null);
    this.selectedRange.set(null);
  }

  protected onWordAction(kind: WordActionKind): void {
    this.wordAnswer.set({
      kind,
      text: `(preview placeholder ${kind} answer — real text arrives with #10+)`,
    });
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
