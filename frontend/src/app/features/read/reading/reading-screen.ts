import {
  Component,
  ElementRef,
  afterRenderEffect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { SumiIcon } from 'sumi-ui/core';
import {
  SumiButtonDirective,
  SumiSubmitOnEnterDirective,
  SumiTextareaDirective,
} from 'sumi-ui/forms';
import {
  SumiBadge,
  SumiFocusModeDirective,
  SumiPopover,
  SumiPopoverHeader,
  SumiShellFocusActionsDirective,
  SumiSidePanel,
} from 'sumi-ui/layout';
import {
  SumiReadingText,
  SumiSessionBar,
  SumiSessionBarActionDirective,
  SumiSessionBarActionLabelDirective,
  type SumiReadingWord,
  type SumiReadingWordActivateEvent,
} from 'sumi-ui/practice';
import type {
  ChatMessage,
  ReadingTextData,
  WordActionKind,
  WordAnswer,
  WordDetails,
} from './reading.types';

/**
 * The reading screen itself: focus mode, `sumi-session-bar` (timer,
 * pause and the projected chat action) in the shell header, the text, and
 * the word lookup / chat overlays. Fully controlled — `selectedWord`/`chatOpen`/`paused` etc. all
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
 * The word popover anchors on the activated word's own element
 * (`wordActivated`'s `element`, sumi-ui#108), so `sumi-popover` can
 * re-measure it on resize and scroll.
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
    SumiSessionBar,
    SumiSessionBarActionDirective,
    SumiSessionBarActionLabelDirective,
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

  /**
   * Whether the session bar's "Ask about this text" chat action is shown
   * at all -- `true` by default so every existing `/preview/reading*`
   * route keeps showing it unchanged. Issue #9 sets this `false`: the
   * tutor chat is #11's own scope, and a button that opens a panel with
   * nothing behind it yet would be worse than no button. `sumi-side-panel`
   * itself stays in the template regardless -- with no way to open it,
   * it simply never does.
   */
  readonly chatEnabled = input(true);

  readonly selectedWord = input<WordDetails | null>(null);
  readonly selectedWordId = input<string | null>(null);
  readonly wordAnswer = input<WordAnswer | null>(null);
  /**
   * The action currently waiting on an answer (issue #10), or `null` when
   * none is -- every action button is disabled while this is set (asking
   * twice at once makes no sense: the second tap could only ever dedupe
   * away or return the same cached answer the first one is already
   * fetching), and the one matching button shows its own loading state.
   */
  readonly wordActionLoading = input<WordActionKind | null>(null);

  readonly chatOpen = input(false);
  readonly chatMessages = input<readonly ChatMessage[]>([]);
  readonly chatSending = input(false);
  /**
   * The next question's focus, already resolved to its display text (e.g.
   * a sentence, truncated) -- `null` for no focus, shown as a small
   * removable chip above the composer (issue #11). Opening the chat from
   * the session bar's own action carries no focus; "Ask tutor" on a word
   * does, until the chip is cleared (explicitly, or by the next question
   * being sent).
   */
  readonly chatFocus = input<string | null>(null);

  readonly wordActivate = output<SumiReadingWordActivateEvent>();
  /** Forwarded straight from `SumiReadingText` — see its own doc comment. */
  readonly readingPeeked = output<SumiReadingWord>();
  readonly closeWord = output<void>();
  readonly wordAction = output<WordActionKind>();
  readonly pauseToggle = output<void>();
  readonly chatToggle = output<void>();
  readonly chatSend = output<string>();
  readonly chatFocusClear = output<void>();
  readonly doneReading = output<void>();

  /** The word span `sumi-popover` anchors next to. */
  protected readonly anchorEl = signal<HTMLElement | null>(null);

  private readonly elementRef = inject(ElementRef<HTMLElement>);

  constructor() {
    // Keep the newest message in view as the conversation grows --
    // `sumi-side-panel`'s own scroll container (`.sumi-side-panel__body`)
    // is in *its* template, not this component's, so there is no local
    // `viewChild` to bind; a plain DOM query for it is unaffected by that
    // boundary (only CSS scoping cares about it). `afterRenderEffect`
    // reruns after every render that this effect's own reads were part of,
    // so a new message/pending bubble is always scrolled to right after it
    // paints.
    afterRenderEffect(() => {
      this.chatMessages();
      this.chatSending();
      const body = this.elementRef.nativeElement.querySelector('.sumi-side-panel__body');
      if (body) {
        body.scrollTop = body.scrollHeight;
      }
    });
  }

  protected onWordActivate(event: SumiReadingWordActivateEvent): void {
    this.anchorEl.set(event.element);
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
}
