// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// Word lookup: an anchored popover next to the tapped word on desktop, a
// bottom sheet on phone — same content, two placements switched by a media
// query, the same way `sumi-session-progress` moves between an inline bar
// and the shell's header strip. Sumi UI has `sumi-dialog` (a centred modal
// on native `<dialog>`) but nothing anchored to an arbitrary element, and
// nothing that turns into a bottom sheet on narrow screens, so this is its
// own overlay rather than a `sumi-dialog` instance.
import { Component, HostListener, computed, input, output, signal } from '@angular/core';
import { NgStyle } from '@angular/common';
import { SUMI_KEYS, SumiIcon, injectHotkey } from 'sumi-ui/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiBadge } from 'sumi-ui/layout';

export type WordActionKind = 'explain' | 'translate' | 'grammar' | 'tutor';

export interface WordActionOption {
  kind: WordActionKind;
  label: string;
  /** Help weight shown as a small hint, e.g. "2" — see the concept's help weights. */
  weight: number;
}

export interface WordDetails {
  word: string;
  reading: string;
  jlptLevel?: string;
  meanings: readonly string[];
  /** e.g. "Kanji Trainer: Guru II" or "Not in Kanji Trainer". */
  knownStatus: string;
  actions: readonly WordActionOption[];
}

export interface WordAnswer {
  kind: WordActionKind;
  text: string;
}

/** The tapped word's screen position, so the desktop popover can anchor
 *  next to it — a plain `DOMRect`-shaped value rather than the element
 *  itself, so this component never has to reach into another component's
 *  DOM directly. */
export interface WordAnchorRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

@Component({
  selector: 'proto-word-popover-sheet',
  templateUrl: './word-popover-sheet.html',
  styleUrl: './word-popover-sheet.scss',
  imports: [NgStyle, SumiIcon, SumiButtonDirective, SumiBadge],
  host: { class: 'proto-word-popover-sheet' },
})
export class WordPopoverSheet {
  readonly word = input<WordDetails | null>(null);
  readonly anchorRect = input<WordAnchorRect | null>(null);
  readonly answer = input<WordAnswer | null>(null);

  readonly close = output<void>();
  readonly action = output<WordActionKind>();

  private readonly viewportWidth = signal(this.readViewportWidth());
  private readonly viewportHeight = signal(this.readViewportHeight());

  constructor() {
    injectHotkey({
      keys: SUMI_KEYS.escape,
      label: 'Close word lookup',
      scope: 'page',
      enabled: () => !!this.word(),
      handler: () => this.close.emit(),
    });
  }

  @HostListener('window:resize')
  protected onResize(): void {
    this.viewportWidth.set(this.readViewportWidth());
    this.viewportHeight.set(this.readViewportHeight());
  }

  /** Desktop only — the popover's own CSS ignores this below the 720px
   *  breakpoint, where it renders as a full-width bottom sheet instead. */
  protected readonly popoverStyle = computed(() => {
    const anchor = this.anchorRect();
    if (!anchor) {
      return {};
    }
    const width = 320;
    const maxLeft = Math.max(8, this.viewportWidth() - width - 8);
    const left = Math.min(maxLeft, Math.max(8, anchor.x));
    const top = Math.min(this.viewportHeight() - 80, anchor.y + anchor.height + 8);
    return { left: `${left}px`, top: `${top}px` };
  });

  protected onAction(kind: WordActionKind): void {
    this.action.emit(kind);
  }

  private readViewportWidth(): number {
    if (typeof window === 'undefined') {
      return 1280;
    }
    return window.innerWidth;
  }

  private readViewportHeight(): number {
    if (typeof window === 'undefined') {
      return 800;
    }
    return window.innerHeight;
  }
}
