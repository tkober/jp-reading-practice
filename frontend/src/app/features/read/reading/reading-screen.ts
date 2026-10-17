import { Component, inject, input, output } from '@angular/core';
import { SumiIcon } from 'sumi-ui/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiFocusModeDirective, SumiShellFocusActionsDirective } from 'sumi-ui/layout';
import { SumiFurigana, SumiFuriganaToggle } from 'sumi-ui/practice';
import { SidePanel, type ChatMessage } from '../../../proto/side-panel/side-panel';
import { TappableRubyText, type WordActivateEvent } from '../../../proto/tappable-ruby-text/tappable-ruby-text';
import {
  WordPopoverSheet,
  type WordActionKind,
  type WordAnchorRect,
  type WordAnswer,
  type WordDetails,
} from '../../../proto/word-popover-sheet/word-popover-sheet';
import type { ReadingTextData } from './reading.types';

/**
 * The reading screen itself: focus mode, the session bar (timer/pause/
 * furigana toggle) in the shell header, the text, and the word lookup /
 * chat overlays. Fully controlled — `selectedWord`/`chatOpen`/`paused` etc.
 * all come from outside, so the host page (#9+) owns the actual session
 * state; this component only renders it and reports interactions.
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
    SumiFuriganaToggle,
    TappableRubyText,
    WordPopoverSheet,
    SidePanel,
  ],
  host: { class: 'app-reading-screen' },
})
export class ReadingScreen {
  /** Injected directly (rather than only used through `sumi-furigana-
   *  toggle`) for the phone header's icon-only toggle button below —
   *  `sumi-furigana-toggle` always renders its own "Furigana" text label,
   *  which has nowhere to go in a one-row compact header. The real
   *  component is still used at ≥720px (see the template). */
  protected readonly furigana = inject(SumiFurigana);

  readonly text = input.required<ReadingTextData>();
  readonly elapsedLabel = input('0:00');
  readonly paused = input(false);
  readonly furiganaEverywhere = input(false);

  readonly selectedWord = input<WordDetails | null>(null);
  readonly selectedWordAnchor = input<WordAnchorRect | null>(null);
  readonly selectedWordId = input<string | null>(null);
  readonly wordAnswer = input<WordAnswer | null>(null);

  readonly chatOpen = input(false);
  readonly chatMessages = input<readonly ChatMessage[]>([]);
  readonly chatSending = input(false);

  readonly wordActivate = output<WordActivateEvent>();
  readonly closeWord = output<void>();
  readonly wordAction = output<WordActionKind>();
  readonly pauseToggle = output<void>();
  readonly chatToggle = output<void>();
  readonly chatSend = output<string>();
  readonly doneReading = output<void>();
}
