import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import {
  DWELL_MS,
  LONG_PRESS_CANCEL_PX,
  LONG_PRESS_MS,
  TappableRubyText,
  type ReadingParagraph,
  type ReadingWord,
  type WordActivateEvent,
} from './tappable-ruby-text';

// A kanji word with a reading (peekable) and a kana-only one (nothing to
// peek — no reading at all), the same shape `showsReading`/`canPeek`
// branch on in the real fixtures.
const KNOWN_WORD: ReadingWord = { id: 'w1', text: '散歩', reading: 'さんぽ' };
const KANA_WORD: ReadingWord = { id: 'w2', text: 'です' };
const PARAGRAPHS: readonly ReadingParagraph[] = [[KNOWN_WORD, KANA_WORD]];

@Component({
  imports: [TappableRubyText],
  template: `
    <proto-tappable-ruby-text
      [paragraphs]="paragraphs()"
      (wordActivate)="activated.push($event)"
      (readingPeeked)="peeked.push($event)"
    />
  `,
})
class HostComponent {
  readonly paragraphs = signal(PARAGRAPHS);
  readonly activated: WordActivateEvent[] = [];
  readonly peeked: ReadingWord[] = [];
}

function render() {
  TestBed.configureTestingModule({ imports: [HostComponent] });
  const fixture = TestBed.createComponent(HostComponent);
  fixture.detectChanges();
  return fixture;
}

function wordSpan(fixture: ReturnType<typeof render>, text: string): HTMLElement {
  const host = fixture.nativeElement as HTMLElement;
  const spans = Array.from(host.querySelectorAll<HTMLElement>('.word'));
  const match = spans.find((span) => span.textContent?.trim().startsWith(text));
  if (!match) {
    throw new Error(`no word span for "${text}"`);
  }
  return match;
}

function hasRuby(span: HTMLElement): boolean {
  return !!span.querySelector('ruby');
}

/** `PointerEvent` may not be constructible in the test DOM — a plain
 *  `Event` with the same fields read by the component (`pointerType`,
 *  `clientX`, `clientY`) behaves identically for its purposes. */
function firePointer(
  el: HTMLElement,
  type: string,
  init: { pointerType: 'mouse' | 'touch'; clientX?: number; clientY?: number },
): void {
  let event: Event;
  try {
    event = new PointerEvent(type, { bubbles: true, cancelable: true, ...init });
  } catch {
    event = Object.assign(new Event(type, { bubbles: true, cancelable: true }), {
      clientX: 0,
      clientY: 0,
      ...init,
    });
  }
  el.dispatchEvent(event);
}

function click(el: HTMLElement): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
}

describe('TappableRubyText — reading peek timing', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not peek a known word on a quick hover that leaves before the dwell', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerenter', { pointerType: 'mouse' });
    vi.advanceTimersByTime(DWELL_MS - 50);
    firePointer(span, 'pointerleave', { pointerType: 'mouse' });
    vi.advanceTimersByTime(200);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(false);
    expect(fixture.componentInstance.peeked).toEqual([]);
  });

  it('peeks a known word after hovering for the full dwell, and hides it on leave', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerenter', { pointerType: 'mouse' });
    vi.advanceTimersByTime(DWELL_MS);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(true);
    expect(fixture.componentInstance.peeked).toEqual([KNOWN_WORD]);

    firePointer(span, 'pointerleave', { pointerType: 'mouse' });
    fixture.detectChanges();
    expect(hasRuby(span)).toBe(false);
  });

  it('emits readingPeeked only once per word across repeated hovers', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerenter', { pointerType: 'mouse' });
    vi.advanceTimersByTime(DWELL_MS);
    firePointer(span, 'pointerleave', { pointerType: 'mouse' });

    firePointer(span, 'pointerenter', { pointerType: 'mouse' });
    vi.advanceTimersByTime(DWELL_MS);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(true);
    expect(fixture.componentInstance.peeked.length).toBe(1);
  });

  it('never peeks a kana-only word (nothing to reveal)', () => {
    const fixture = render();
    const span = wordSpan(fixture, 'です');

    firePointer(span, 'pointerenter', { pointerType: 'mouse' });
    vi.advanceTimersByTime(DWELL_MS + 100);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(false);
    expect(fixture.componentInstance.peeked).toEqual([]);
  });

  it('peeks a known word after keyboard focus for the full dwell, and hides it on blur', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    span.dispatchEvent(new FocusEvent('focus', { bubbles: true }));
    vi.advanceTimersByTime(DWELL_MS);
    fixture.detectChanges();
    expect(hasRuby(span)).toBe(true);

    span.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
    fixture.detectChanges();
    expect(hasRuby(span)).toBe(false);
  });

  it('activates (opens the popover) on a short tap, with no peek', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerdown', { pointerType: 'touch', clientX: 100, clientY: 100 });
    vi.advanceTimersByTime(LONG_PRESS_MS - 100);
    firePointer(span, 'pointerup', { pointerType: 'touch', clientX: 100, clientY: 100 });
    click(span);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(false);
    expect(fixture.componentInstance.peeked).toEqual([]);
    expect(fixture.componentInstance.activated.length).toBe(1);
    expect(fixture.componentInstance.activated[0].word).toEqual(KNOWN_WORD);
  });

  it('peeks on a long press and suppresses the click that follows it, instead of also activating', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerdown', { pointerType: 'touch', clientX: 100, clientY: 100 });
    vi.advanceTimersByTime(LONG_PRESS_MS);
    fixture.detectChanges();
    expect(hasRuby(span)).toBe(true);
    expect(fixture.componentInstance.peeked.length).toBe(1);

    firePointer(span, 'pointerup', { pointerType: 'touch', clientX: 100, clientY: 100 });
    fixture.detectChanges();
    expect(hasRuby(span)).toBe(false);

    // Touch still fires a `click` after `pointerup` even though nothing
    // here asked for one — it must not also open the word popover.
    click(span);
    expect(fixture.componentInstance.activated).toEqual([]);
  });

  it('cancels the long press once the touch moves more than the cancel threshold (a scroll)', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerdown', { pointerType: 'touch', clientX: 100, clientY: 100 });
    vi.advanceTimersByTime(LONG_PRESS_MS / 2);
    firePointer(span, 'pointermove', {
      pointerType: 'touch',
      clientX: 100,
      clientY: 100 + LONG_PRESS_CANCEL_PX + 1,
    });
    vi.advanceTimersByTime(LONG_PRESS_MS);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(false);
    expect(fixture.componentInstance.peeked).toEqual([]);
  });

  it('a small jitter under the cancel threshold does not cancel the long press', () => {
    const fixture = render();
    const span = wordSpan(fixture, '散歩');

    firePointer(span, 'pointerdown', { pointerType: 'touch', clientX: 100, clientY: 100 });
    vi.advanceTimersByTime(LONG_PRESS_MS / 2);
    firePointer(span, 'pointermove', {
      pointerType: 'touch',
      clientX: 100,
      clientY: 100 + LONG_PRESS_CANCEL_PX - 1,
    });
    vi.advanceTimersByTime(LONG_PRESS_MS / 2);
    fixture.detectChanges();

    expect(hasRuby(span)).toBe(true);
  });
});
