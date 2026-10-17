// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// A side panel next to the main content on desktop, a full-height sheet on
// phone — the chat-about-this-text panel's shape. Sumi UI has `sumi-dialog`
// (centred, fixed size) and `sumi-app-shell`'s own tab-bar "More" sheet, but
// no general-purpose docked/sheet drawer a page can place next to its own
// content. The host only renders while a parent `@if`s it in, so there is
// nothing to animate open/closed here yet — the library version would
// likely want that.
import {
  Component,
  DestroyRef,
  PLATFORM_ID,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { SUMI_KEYS, SumiIcon, injectHotkey } from 'sumi-ui/core';
import { SumiButtonDirective, SumiTextareaDirective } from 'sumi-ui/forms';

/** Matches the `@media (max-width: 720px)` breakpoint in `side-panel.scss`,
 *  where this becomes a full-screen sheet instead of a docked panel. */
const NARROW_QUERY = '(max-width: 720px)';

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

@Component({
  selector: 'proto-side-panel',
  templateUrl: './side-panel.html',
  styleUrl: './side-panel.scss',
  imports: [SumiIcon, SumiButtonDirective, SumiTextareaDirective],
  host: {
    class: 'proto-side-panel',
    '[style.top.px]': 'topPx()',
    '[style.height]': 'heightStyle()',
  },
})
export class SidePanel {
  readonly title = input('Ask about this text');
  readonly messages = input<readonly ChatMessage[]>([]);
  readonly sending = input(false);

  readonly close = output<void>();
  readonly send = output<string>();

  protected readonly draft = signal('');
  protected readonly canSend = computed(() => this.draft().trim().length > 0 && !this.sending());

  /** The shell header's own rendered height, measured so the fixed panel
   *  sits flush below it and fills exactly the rest of the viewport on
   *  desktop — the header is `position: sticky` within `sumi-app-shell__
   *  main`'s own scroll container, not the window, so a plain CSS
   *  `top: 0; height: 100vh` cannot be computed relative to it from here
   *  without this. Unused (and not measured) below the 720px breakpoint,
   *  where this becomes a full-screen sheet instead (see the scss) and
   *  must ignore the header entirely. */
  private readonly headerHeight = signal(0);
  private readonly narrow = signal(this.readNarrow());

  protected readonly topPx = computed<number | null>(() => (this.narrow() ? null : this.headerHeight()));
  protected readonly heightStyle = computed<string | null>(() =>
    this.narrow() ? null : `calc(100vh - ${this.headerHeight()}px)`,
  );

  constructor() {
    const destroyRef = inject(DestroyRef);
    const platformId = inject(PLATFORM_ID);

    injectHotkey({
      keys: SUMI_KEYS.escape,
      label: 'Close chat',
      scope: 'page',
      handler: () => this.close.emit(),
    });

    if (!isPlatformBrowser(platformId)) {
      return;
    }

    const query = matchMedia(NARROW_QUERY);
    const onChange = (event: MediaQueryListEvent) => this.narrow.set(event.matches);
    query.addEventListener('change', onChange);
    destroyRef.onDestroy(() => query.removeEventListener('change', onChange));

    afterNextRender(() => {
      const header = document.querySelector<HTMLElement>('.sumi-app-shell__sticky');
      if (!header || typeof ResizeObserver === 'undefined') {
        return;
      }
      this.headerHeight.set(header.offsetHeight);
      const observer = new ResizeObserver(() => this.headerHeight.set(header.offsetHeight));
      observer.observe(header);
      destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  private readNarrow(): boolean {
    return typeof matchMedia === 'function' && matchMedia(NARROW_QUERY).matches;
  }

  protected onSend(): void {
    const text = this.draft().trim();
    if (!text || this.sending()) {
      return;
    }
    this.send.emit(text);
    this.draft.set('');
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.onSend();
    }
  }
}
