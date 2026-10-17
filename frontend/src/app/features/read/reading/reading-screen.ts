import { Component, input, output, signal } from '@angular/core';
import { SumiIcon } from 'sumi-ui/core';
import { SumiButtonDirective, SumiSubmitOnEnterDirective, SumiTextareaDirective } from 'sumi-ui/forms';
import {
  SumiBadge,
  SumiFocusModeDirective,
  SumiPopover,
  SumiPopoverHeader,
  SumiShellFocusActionsDirective,
  SumiSidePanel,
} from 'sumi-ui/layout';
import { SumiReadingText, type SumiReadingWord, type SumiReadingWordActivateEvent } from 'sumi-ui/practice';
import type { ChatMessage, ReadingTextData, WordActionKind, WordAnswer, WordDetails } from './reading.types';

/**
 * The reading screen itself: focus mode, the session bar (timer/pause/
 * chat) in the shell header, the text, and the word lookup / chat
 * overlays. Fully controlled — `selectedWord`/`chatOpen`/`paused` etc. all
 * come from outside, so the host page (#9+) owns the actual session state;
 * this component only renders it and reports interactions.
 *
 * There is deliberately no app-wide furigana on/off control in this bar
 * any more (it used to sit next to pause/chat): with per-word reading
 * peeks now in the text itself (see `SumiReadingText`), a second,
 * app-wide furigana toggle right next to it would be two different
 * "furigana" concepts competing for the same spot in one small header.
 * That preference — whether ruby shows at all, for unknown words and
 * peeks alike (`SumiFurigana`, still read by `SumiReadingText` directly)
 * — belongs in Settings instead, once a later issue adds it there.
 *
 * `sumi-popover`'s `anchor` input wants a live `HTMLElement`, not the
 * static `DOMRect` snapshot `SumiReadingText`'s `wordActivated` event
 * carries — see `resolveAnchorElement`'s doc comment for how this bridges
 * the two (a documented library gap, see the PR notes).
 */
@Component({
  selector: 'app-reading-screen',
  templateUrl: './reading-screen.html',
  styleUrl: './reading-screen.scss',
  imports: [
    SumiFocusModeDirective,
    SumiShellFocusActionsDirective,
    SumiIcon,
    SumiButtonDirective,
    SumiReadingText,
    SumiPopover,
    SumiPopoverHeader,
    SumiBadge,
    SumiSidePanel,
    SumiTextareaDirective,
    SumiSubmitOnEnterDirective,
  ],
  host: { class: 'app-reading-screen' },
})
export class ReadingScreen {
  readonly text = input.required<ReadingTextData>();
  readonly elapsedLabel = input('0:00');
  readonly paused = input(false);

  readonly selectedWord = input<WordDetails | null>(null);
  readonly selectedWordId = input<string | null>(null);
  readonly wordAnswer = input<WordAnswer | null>(null);

  readonly chatOpen = input(false);
  readonly chatMessages = input<readonly ChatMessage[]>([]);
  readonly chatSending = input(false);

  readonly wordActivate = output<SumiReadingWordActivateEvent>();
  /** Forwarded straight from `SumiReadingText` — see its own doc comment. */
  readonly readingPeeked = output<SumiReadingWord>();
  readonly closeWord = output<void>();
  readonly wordAction = output<WordActionKind>();
  readonly pauseToggle = output<void>();
  readonly chatToggle = output<void>();
  readonly chatSend = output<string>();
  readonly doneReading = output<void>();

  /** The word span `sumi-popover` anchors next to — resolved from the
   *  activated word's rect, see `onWordActivate`. */
  protected readonly anchorEl = signal<HTMLElement | null>(null);

  protected onWordActivate(event: SumiReadingWordActivateEvent): void {
    this.anchorEl.set(this.resolveAnchorElement(event.rect));
    this.wordActivate.emit(event);
  }

  protected onPopoverOpenChange(open: boolean): void {
    if (!open) {
      this.closeWord.emit();
    }
  }

  protected onChatOpenChange(open: boolean): void {
    if (!open) {
      this.chatToggle.emit();
    }
  }

  protected onChatSend(value: string, input: HTMLTextAreaElement): void {
    const text = value.trim();
    if (!text) {
      return;
    }
    this.chatSend.emit(text);
    input.value = '';
  }

  /**
   * `SumiReadingText`'s `wordActivated` event gives only the activated
   * word's `DOMRect` (see its own doc comment) — there is no reference to
   * the actual word `<span>` to hand `sumi-popover`'s `[anchor]` input,
   * which needs a live `HTMLElement` so it can re-measure on resize/scroll
   * (see that component's own doc comment). `document.elementFromPoint`
   * at the rect's centre resolves back to it without reaching into the
   * library's own DOM structure by class name — every word is documented
   * as its own `role="button"` element (see `SumiReadingText`'s header
   * comment), which is the one thing this relies on. A cleaner library
   * fix would have `wordActivated` carry the element itself.
   */
  private resolveAnchorElement(rect: DOMRect): HTMLElement | null {
    if (typeof document === 'undefined') {
      return null;
    }
    const target = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return (target as HTMLElement | null)?.closest<HTMLElement>('[role="button"]') ?? null;
  }
}
