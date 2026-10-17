import { Component, input, output } from '@angular/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiFocusModeDirective, SumiShellFocusActionsDirective } from 'sumi-ui/layout';
import { SumiFuriganaToggle } from 'sumi-ui/practice';
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
    SumiButtonDirective,
    SumiFuriganaToggle,
    TappableRubyText,
    WordPopoverSheet,
    SidePanel,
  ],
  host: { class: 'app-reading-screen' },
})
export class ReadingScreen {
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
