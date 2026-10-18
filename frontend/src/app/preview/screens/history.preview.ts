import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { HistoryScreen } from '../../features/history/history-screen';
import { HISTORY_SESSIONS } from '../fixtures/history.fixture';

export type HistoryPreviewVariant = 'default' | 'empty';

@Component({
  selector: 'preview-history',
  template: `
    <app-history-screen
      [sessions]="sessions()"
      (openSession)="opened.set($event)"
      (exportRequested)="exported.set(true)"
    />
    @if (opened(); as id) {
      <p class="preview-note">→ would open session "{{ id }}"</p>
    }
    @if (exported()) {
      <p class="preview-note">→ would download the JSON export</p>
    }
  `,
  styles: [
    '.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }',
  ],
  imports: [HistoryScreen],
})
export class HistoryPreview {
  protected readonly sessions = signal(HISTORY_SESSIONS);
  protected readonly opened = signal<string | null>(null);
  protected readonly exported = signal(false);

  constructor() {
    const variant = (inject(ActivatedRoute).snapshot.data['variant'] ??
      'default') as HistoryPreviewVariant;
    if (variant === 'empty') {
      this.sessions.set([]);
    }
  }
}
