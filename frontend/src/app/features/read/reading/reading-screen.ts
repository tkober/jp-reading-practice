import { Component, input, output } from '@angular/core';
import { SumiIcon } from 'sumi-ui/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiFocusModeDirective, SumiShellFocusActionsDirective } from 'sumi-ui/layout';
import { SidePanel, type ChatMessage } from '../../../proto/side-panel/side-panel';
import {
  TappableRubyText,
  type ReadingWord,
  type WordActivateEvent,
} from '../../../proto/tappable-ruby-text/tappable-ruby-text';
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
 * chat) in the shell header, the text, and the word lookup / chat
 * overlays. Fully controlled — `selectedWord`/`chatOpen`/`paused` etc. all
 * come from outside, so the host page (#9+) owns the actual session state;
 * this component only renders it and reports interactions.
 *
 * There is deliberately no app-wide furigana on/off control in this bar
 * any more (it used to sit next to pause/chat): with per-word reading
 * peeks now in the text itself (see `TappableRubyText`), a second,
 * app-wide furigana toggle right next to it would be two different
 * "furigana" concepts competing for the same spot in one small header.
 * That preference — whether ruby shows at all, for unknown words and
 * peeks alike (`SumiFurigana`, still read by `TappableRubyText` directly)
 * — belongs in Settings instead, once a later issue adds it there.
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
  /** Preview-only — see `TappableRubyText.forcePeekWordId`'s doc comment;
   *  forwarded straight through, never set outside the design preview. */
  readonly previewForcePeekWordId = input<string | null>(null);

  readonly selectedWord = input<WordDetails | null>(null);
  readonly selectedWordAnchor = input<WordAnchorRect | null>(null);
  readonly selectedWordId = input<string | null>(null);
  readonly wordAnswer = input<WordAnswer | null>(null);

  readonly chatOpen = input(false);
  readonly chatMessages = input<readonly ChatMessage[]>([]);
  readonly chatSending = input(false);

  readonly wordActivate = output<WordActivateEvent>();
  /** Forwarded straight from `TappableRubyText` — see its own doc comment. */
  readonly readingPeeked = output<ReadingWord>();
  readonly closeWord = output<void>();
  readonly wordAction = output<WordActionKind>();
  readonly pauseToggle = output<void>();
  readonly chatToggle = output<void>();
  readonly chatSend = output<string>();
  readonly doneReading = output<void>();
}
