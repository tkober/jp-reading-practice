import { Component, signal } from '@angular/core';
import { GateScreen } from '../../features/read/gate/gate-screen';
import { READING_TEXT } from '../fixtures/reading-text.fixture';

@Component({
  selector: 'preview-gate',
  template: `
    <app-gate-screen
      [titleJapanese]="titleJapanese"
      [characterCount]="545"
      [estimatedMinutes]="4"
      [unknownKanjiPercent]="4"
      [jlptMix]="jlptMix"
      (start)="started.set(true)"
    />
    @if (started()) {
      <p class="preview-note">→ would navigate to /preview/reading</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [GateScreen],
})
export class GatePreview {
  protected readonly titleJapanese = READING_TEXT.titleJapanese;
  protected readonly jlptMix = { n5: 45, n4: 38, n3: 17, n2: 0, n1: 0 };
  protected readonly started = signal(false);
}
