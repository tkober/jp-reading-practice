import { Component, signal } from '@angular/core';
import { GenerationFailedScreen } from '../../features/read/error/generation-failed-screen';

@Component({
  selector: 'preview-generation-failed',
  template: `
    <app-generation-failed-screen (retry)="action.set('retry')" (backToSetup)="action.set('back to setup')" />
    @if (action(); as a) {
      <p class="preview-note">→ {{ a }}</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [GenerationFailedScreen],
})
export class GenerationFailedPreview {
  protected readonly action = signal<string | null>(null);
}
