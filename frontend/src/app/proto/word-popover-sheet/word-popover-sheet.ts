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
import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  afterRenderEffect,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
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
  /** Omitted (or equal to `word`) for a kana-only word, where repeating it
   *  as a separate reading line would say nothing new. */
  reading?: string;
  jlptLevel?: string;
  meanings: readonly string[];
  /** e.g. "Kanji Trainer: Guru II" or "Not in Kanji Trainer" — only shown
   *  for `kind: 'word'` (the default); a grammar pattern has no Kanji
   *  Trainer status of its own. */
  knownStatus?: string;
  actions: readonly WordActionOption[];
  /** `'word'` (default) looks up a single word, with a JLPT badge and
   *  Kanji Trainer status; `'grammar'` looks up a grammar pattern instead
   *  — shown with a "Grammar" badge and no Kanji Trainer line. */
  kind?: 'word' | 'grammar';
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

  /** The rendered panel, measured so `popoverStyle` can tell whether it
   *  actually fits below the word before committing to that placement —
   *  see the class doc comment on why this exists at all. */
  private readonly panelRef = viewChild<ElementRef<HTMLElement>>('panelRef');
  private readonly panelHeight = signal(0);

  constructor() {
    injectHotkey({
      keys: SUMI_KEYS.escape,
      label: 'Close word lookup',
      scope: 'page',
      enabled: () => !!this.word(),
      handler: () => this.close.emit(),
    });

    const destroyRef = inject(DestroyRef);
    let observer: ResizeObserver | undefined;
    afterRenderEffect(() => {
      const element = this.panelRef()?.nativeElement;
      observer?.disconnect();
      observer = undefined;
      if (!element || typeof ResizeObserver === 'undefined') {
        this.panelHeight.set(0);
        return;
      }
      this.panelHeight.set(element.offsetHeight);
      observer = new ResizeObserver(() => this.panelHeight.set(element.offsetHeight));
      observer.observe(element);
    });
    destroyRef.onDestroy(() => observer?.disconnect());
  }

  @HostListener('window:resize')
  protected onResize(): void {
    this.viewportWidth.set(this.readViewportWidth());
    this.viewportHeight.set(this.readViewportHeight());
  }

  /** Desktop only — the popover's own CSS ignores this below the 720px
   *  breakpoint, where it renders as a full-width bottom sheet instead.
   *  Prefers opening below the word (reading order, least surprising);
   *  flips above only once the measured panel genuinely does not fit in
   *  the space below, and either way never overlaps the word itself —
   *  the gap is always kept on the side facing the word. */
  protected readonly popoverStyle = computed(() => {
    const anchor = this.anchorRect();
    if (!anchor) {
      return {};
    }
    const width = 320;
    const gap = 8;
    const viewportWidth = this.viewportWidth();
    const viewportHeight = this.viewportHeight();
    const height = this.panelHeight();

    const maxLeft = Math.max(gap, viewportWidth - width - gap);
    const left = Math.min(maxLeft, Math.max(gap, anchor.x));

    const spaceBelow = viewportHeight - (anchor.y + anchor.height) - gap;
    // `height` is 0 before the panel has been measured once — default to
    // "below" rather than flipping on a guess.
    const fitsBelow = height === 0 || spaceBelow >= height;
    const top = fitsBelow
      ? anchor.y + anchor.height + gap
      : Math.max(gap, anchor.y - height - gap);

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
