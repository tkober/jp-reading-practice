import { Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

import { Api } from '../../core/api';
import type { HistoryEntryApi } from '../../core/api.types';
import { isBackendUnreachable } from '../../core/unreachable';
import { HistoryScreen } from '../../features/history/history-screen';
import { toHistorySession } from './history-mapping';

/**
 * Wires `features/history/` (the approved design) into the real `/history`
 * route against `GET /api/history` (issue #12). One screen, no sub-mode:
 * unlike Topics/Settings there is nothing to edit here, just load, show,
 * and act on a row/the export button.
 */
@Component({
  selector: 'app-history',
  imports: [...SUMI_LAYOUT, HistoryScreen, SumiButtonDirective],
  templateUrl: './history.html',
})
export class HistoryPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  protected readonly loading = signal(true);
  /** The history itself could not be loaded at all -- T6, not a banner. */
  protected readonly failed = signal(false);
  protected readonly loadError = signal<string | null>(null);

  private readonly entries = signal<readonly HistoryEntryApi[]>([]);
  // Oldest first, matching `HistoryScreen.sessions`' own contract (it
  // reverses the list itself to show newest first).
  protected readonly sessions = computed(() => this.entries().map(toHistorySession));

  protected readonly exportError = signal<string | null>(null);
  protected readonly exporting = signal(false);

  constructor() {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.api.history().then(
      (entries) => {
        this.loading.set(false);
        this.failed.set(false);
        this.loadError.set(null);
        this.entries.set(entries);
      },
      (error: unknown) => {
        this.loading.set(false);
        if (isBackendUnreachable(error)) {
          this.failed.set(true);
        } else {
          this.loadError.set((error as Error).message);
        }
      },
    );
  }

  openSession(id: string): void {
    this.router.navigate(['/read', id]);
  }

  /** Fetches `GET /api/export` and triggers a browser download of
   *  `jp-reading-practice-<date>.json` -- a plain Blob + object URL, no
   *  server-side file to clean up (`URL.revokeObjectURL` right after the
   *  click, per the brief). */
  async exportData(): Promise<void> {
    if (this.exporting()) {
      return;
    }
    this.exporting.set(true);
    this.exportError.set(null);
    try {
      const data = await this.api.export();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = `jp-reading-practice-${new Date().toISOString().slice(0, 10)}.json`;
        link.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (error) {
      this.exportError.set((error as Error).message);
    } finally {
      this.exporting.set(false);
    }
  }
}
