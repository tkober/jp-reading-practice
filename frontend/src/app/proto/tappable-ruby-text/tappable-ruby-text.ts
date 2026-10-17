// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// Japanese body text as a sequence of tappable words, each optionally shown
// with ruby furigana. Sumi UI's `sumi-furigana` (`practice/furigana`)
// already renders a run of `{ base, reading }` segments with ruby and ties
// their visibility to the shared `SumiFurigana` service, but it has no
// per-word interactivity — there is nothing to hang a tap/click or a
// keyboard-reachable hit target off inside one `sumi-furigana` instance.
// This renders each word as its own focusable button instead (plain
// `<ruby>`/`<rt>`, not `sumi-furigana`), so word lookup can work, while
// still reading the same `SumiFurigana.visible()` toggle so turning
// furigana off app-wide also hides it here.
//
// `unknown` words always get a reading when one is set; `furiganaEverywhere`
// (this app's "show furigana everywhere" help, costed separately from the
// shared on/off preference) adds it to known words too, for words whose
// fixture happens to carry a reading. Toggling furigana off globally still
// wins over both — nothing shows if the learner turned readings off
// entirely.
import { Component, ElementRef, QueryList, ViewChildren, inject, input, output } from '@angular/core';
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

@Component({
  selector: 'proto-tappable-ruby-text',
  templateUrl: './tappable-ruby-text.html',
  styleUrl: './tappable-ruby-text.scss',
  host: { class: 'proto-tappable-ruby-text', lang: 'ja' },
})
export class TappableRubyText {
  protected readonly furigana = inject(SumiFurigana);

  readonly paragraphs = input.required<readonly ReadingParagraph[]>();
  readonly furiganaEverywhere = input(false);
  readonly selectedWordId = input<string | null>(null);

  readonly wordActivate = output<WordActivateEvent>();

  @ViewChildren('wordRef')
  private readonly wordRefs?: QueryList<ElementRef<HTMLButtonElement>>;

  protected showsReading(word: ReadingWord): boolean {
    if (!word.reading || !this.furigana.visible()) {
      return false;
    }
    return !!word.unknown || this.furiganaEverywhere();
  }

  protected onActivate(word: ReadingWord, event: MouseEvent): void {
    const target = event.currentTarget as HTMLElement;
    this.wordActivate.emit({ word, rect: target.getBoundingClientRect() });
  }

  /** Left/Right/Up/Down move focus between word buttons; Home/End jump to
   *  the first/last word — the reading text has no other roving-tabindex
   *  control, so plain arrow-key navigation across a flat list of buttons
   *  is enough (unlike `sumi-segmented-control`, there is no "selected"
   *  option to track). */
  protected onKeydown(event: KeyboardEvent, flatIndex: number): void {
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
