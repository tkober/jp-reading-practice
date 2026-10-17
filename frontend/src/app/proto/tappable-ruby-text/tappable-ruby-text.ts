// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// Japanese body text as a sequence of tappable words, each optionally shown
// with ruby furigana. Sumi UI's `sumi-furigana` (`practice/furigana`)
// already renders a run of `{ base, reading }` segments with ruby and ties
// their visibility to the shared `SumiFurigana` service, but it has no
// per-word interactivity — there is nothing to hang a tap/click or a
// keyboard-reachable hit target off inside one `sumi-furigana` instance.
// This renders each word as its own focusable element instead (plain
// `<ruby>`/`<rt>`, not `sumi-furigana`), so word lookup can work, while
// still reading the same `SumiFurigana.visible()` toggle so turning
// furigana off app-wide also hides it here.
//
// Each word is a `<span role="button" tabindex="0">`, not a real
// `<button>`: a `<button>` (like `<input>`/`<select>`) is an *atomic*
// inline-level box per the CSS box model — its entire text content is one
// indivisible unit for line-breaking, so a multi-character word that does
// not fit the remaining line width jumps to the next line whole, leaving a
// large ragged gap rather than breaking between its own characters the way
// Japanese text normally does. A plain inline `<span>` has no such
// restriction and participates in ordinary Unicode line-breaking
// (`line-break: strict`, the default CJK-aware behaviour) like any other
// text, while `role="button"` + `tabindex="0"` + explicit key handling keep
// it just as keyboard-reachable and announced the same way a button would
// be.
//
// `unknown` words always get a reading, free, from the start. A *known*
// word with a reading can still be peeked at: hovering it (desktop) or
// focusing it (keyboard) for `DWELL_MS` shows its ruby for as long as the
// pointer/focus stays, then hides it again — a long press does the same on
// touch (`LONG_PRESS_MS`), cancelled by moving more than
// `LONG_PRESS_CANCEL_PX` (a scroll, not a press). Each word's first peek
// emits `readingPeeked` once (a costed help, logged by whoever hosts this
// — see the concept's help weights); later peeks of the same word in the
// same session are free, same as a real dictionary lookup only "costing"
// once. Toggling furigana off globally still wins over all of this —
// nothing shows if the learner turned readings off entirely.
import {
  Component,
  DestroyRef,
  ElementRef,
  QueryList,
  ViewChildren,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { SumiFurigana } from 'sumi-ui/practice';

export interface ReadingWord {
  id: string;
  text: string;
  reading?: string;
  unknown?: boolean;
}

export type ReadingParagraph = readonly ReadingWord[];

export interface WordActivateEvent {
  word: ReadingWord;
  /** The tapped word's own screen position, for an anchored popover. */
  rect: DOMRect;
}

/** How long a hover (desktop) or keyboard focus has to sit on a known word
 *  before its reading peeks into view. */
export const DWELL_MS = 500;
/** How long a touch has to hold a known word before the same happens. */
export const LONG_PRESS_MS = 400;
/** A touch moving more than this many px while held cancels the long
 *  press — it is a scroll, not a press. */
export const LONG_PRESS_CANCEL_PX = 8;

function distance(x1: number, y1: number, x2: number, y2: number): number {
  return Math.hypot(x2 - x1, y2 - y1);
}

@Component({
  selector: 'proto-tappable-ruby-text',
  templateUrl: './tappable-ruby-text.html',
  styleUrl: './tappable-ruby-text.scss',
  host: { class: 'proto-tappable-ruby-text', lang: 'ja' },
})
export class TappableRubyText {
  protected readonly furigana = inject(SumiFurigana);

  readonly paragraphs = input.required<readonly ReadingParagraph[]>();
  readonly selectedWordId = input<string | null>(null);
  /** Preview-only: statically shows this word's reading as already
   *  peeking, for `/preview/reading-peek` — a direct page load has no real
   *  hover/long-press to show, see that route's wrapper. Never set outside
   *  the design preview. */
  readonly forcePeekWordId = input<string | null>(null);

  readonly wordActivate = output<WordActivateEvent>();
  /** A word's reading was peeked at for the first time this session — a
   *  help of weight 1 (see the concept), logged by whoever hosts this. */
  readonly readingPeeked = output<ReadingWord>();

  @ViewChildren('wordRef')
  private readonly wordRefs?: QueryList<ElementRef<HTMLElement>>;

  /** The one word currently peeking (hover/focus dwell or a fired long
   *  press), or `null`. Only ever one at a time — a pointer/keyboard focus
   *  is itself singular. */
  protected readonly peekingWordId = signal<string | null>(null);
  /** The one word currently held down by touch, for suppressing the
   *  native long-press callout/selection on just that word while it is
   *  pressed (see the template/scss) — set from the first `pointerdown`,
   *  regardless of whether it ends up peeking. */
  protected readonly pressingWordId = signal<string | null>(null);

  /** Word ids that have already peeked once this session — a peek only
   *  costs a help the first time (see the class doc comment). */
  private readonly peekedWordIds = new Set<string>();

  private readonly dwellTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private longPressTimer: ReturnType<typeof setTimeout> | undefined;
  private touchStart: { wordId: string; x: number; y: number } | undefined;
  private longPressFired = false;
  /** Set when a long press just fired and consumed by the very next
   *  `click` — on touch, a `click` still follows `pointerup` even though
   *  this component never asked for one, and a long press must not *also*
   *  open the word popover. */
  private suppressNextClick = false;

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      this.dwellTimers.forEach((timer) => clearTimeout(timer));
      this.dwellTimers.clear();
      this.clearLongPress();
    });
  }

  protected showsReading(word: ReadingWord): boolean {
    if (!word.reading || !this.furigana.visible()) {
      return false;
    }
    return !!word.unknown || this.peekingWordId() === word.id || this.forcePeekWordId() === word.id;
  }

  /** Only a known word with a reading can be peeked at — an unknown word
   *  already shows its reading for free, and a word with no reading at all
   *  (kana only) has nothing to reveal. */
  private canPeek(word: ReadingWord): boolean {
    return !!word.reading && !word.unknown;
  }

  private startPeek(word: ReadingWord): void {
    this.peekingWordId.set(word.id);
    if (!this.peekedWordIds.has(word.id)) {
      this.peekedWordIds.add(word.id);
      this.readingPeeked.emit(word);
    }
  }

  private endPeek(wordId: string): void {
    if (this.peekingWordId() === wordId) {
      this.peekingWordId.set(null);
    }
  }

  private clearDwell(wordId: string): void {
    const timer = this.dwellTimers.get(wordId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.dwellTimers.delete(wordId);
    }
  }

  private clearLongPress(): void {
    if (this.longPressTimer !== undefined) {
      clearTimeout(this.longPressTimer);
      this.longPressTimer = undefined;
    }
  }

  // --- desktop: hover dwell -----------------------------------------------

  protected onPointerEnter(event: PointerEvent, word: ReadingWord): void {
    if (event.pointerType !== 'mouse' || !this.canPeek(word)) {
      return;
    }
    this.clearDwell(word.id);
    this.dwellTimers.set(
      word.id,
      setTimeout(() => this.startPeek(word), DWELL_MS),
    );
  }

  protected onPointerLeave(event: PointerEvent, word: ReadingWord): void {
    if (event.pointerType !== 'mouse') {
      return;
    }
    this.clearDwell(word.id);
    this.endPeek(word.id);
  }

  // --- keyboard: focus dwell -----------------------------------------------

  protected onFocus(word: ReadingWord): void {
    if (!this.canPeek(word)) {
      return;
    }
    this.clearDwell(word.id);
    this.dwellTimers.set(
      word.id,
      setTimeout(() => this.startPeek(word), DWELL_MS),
    );
  }

  protected onBlur(word: ReadingWord): void {
    this.clearDwell(word.id);
    this.endPeek(word.id);
  }

  // --- touch: long press -----------------------------------------------

  protected onPointerDown(event: PointerEvent, word: ReadingWord): void {
    if (event.pointerType === 'mouse') {
      return;
    }
    // Suppresses the native long-press callout/selection on this word
    // alone (see the scss) regardless of whether it turns out peekable.
    this.pressingWordId.set(word.id);
    if (!this.canPeek(word)) {
      return;
    }
    this.touchStart = { wordId: word.id, x: event.clientX, y: event.clientY };
    this.longPressFired = false;
    this.clearLongPress();
    this.longPressTimer = setTimeout(() => {
      this.longPressFired = true;
      this.startPeek(word);
    }, LONG_PRESS_MS);
  }

  protected onPointerMove(event: PointerEvent, word: ReadingWord): void {
    if (event.pointerType === 'mouse' || !this.touchStart || this.touchStart.wordId !== word.id) {
      return;
    }
    if (distance(this.touchStart.x, this.touchStart.y, event.clientX, event.clientY) > LONG_PRESS_CANCEL_PX) {
      // A scroll, not a press: cancel outright, including a peek that may
      // have already started, and let the browser scroll normally.
      this.clearLongPress();
      this.endPeek(word.id);
      this.touchStart = undefined;
    }
  }

  protected onPointerUp(event: PointerEvent, word: ReadingWord): void {
    if (event.pointerType === 'mouse') {
      return;
    }
    this.pressingWordId.set(null);
    this.clearLongPress();
    if (this.longPressFired) {
      this.endPeek(word.id);
      this.suppressNextClick = true;
    }
    this.touchStart = undefined;
    this.longPressFired = false;
  }

  protected onPointerCancel(word: ReadingWord): void {
    this.pressingWordId.set(null);
    this.clearLongPress();
    this.endPeek(word.id);
    this.touchStart = undefined;
    this.longPressFired = false;
    // A cancelled gesture (e.g. an incoming scroll/system gesture) must not
    // activate the word either.
    this.suppressNextClick = true;
  }

  // --- activation -----------------------------------------------

  protected onActivate(word: ReadingWord, event: Event): void {
    if (this.suppressNextClick) {
      this.suppressNextClick = false;
      return;
    }
    const target = event.currentTarget as HTMLElement;
    this.wordActivate.emit({ word, rect: target.getBoundingClientRect() });
  }

  /** `Enter`/`Space` activate a word, same as a native button's click would
   *  — needed since a `role="button"` span gets no such behaviour for
   *  free. Left/Right/Up/Down move focus between word spans; Home/End jump
   *  to the first/last word — the reading text has no other roving-
   *  tabindex control, so plain arrow-key navigation across a flat list is
   *  enough (unlike `sumi-segmented-control`, there is no "selected"
   *  option to track). */
  protected onKeydown(event: KeyboardEvent, word: ReadingWord, flatIndex: number): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.onActivate(word, event);
      return;
    }

    const refs = this.wordRefs;
    if (!refs || refs.length === 0) {
      return;
    }
    let nextIndex: number | undefined;
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        nextIndex = Math.min(refs.length - 1, flatIndex + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        nextIndex = Math.max(0, flatIndex - 1);
        break;
      case 'Home':
        nextIndex = 0;
        break;
      case 'End':
        nextIndex = refs.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    refs.get(nextIndex)?.nativeElement.focus();
  }

  /** Flat index of `(paragraphIndex, wordIndex)` across all paragraphs, for
   *  `onKeydown`'s arrow navigation — paragraph boundaries are not a
   *  meaningful stop, the words just keep going. */
  protected flatIndex(paragraphIndex: number, wordIndex: number): number {
    const paragraphs = this.paragraphs();
    let index = 0;
    for (let p = 0; p < paragraphIndex; p++) {
      index += paragraphs[p].length;
    }
    return index + wordIndex;
  }
}
