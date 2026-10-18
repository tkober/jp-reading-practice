import { Component, computed, inject, signal } from '@angular/core';
import type { SumiBar, SumiLinePoint } from 'sumi-ui/charts';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

import { Api } from '../../core/api';
import type { StatsApi } from '../../core/api.types';
import { isBackendUnreachable } from '../../core/unreachable';
import { StatsScreen } from '../../features/stats/stats-screen';
import type { ProblemWord, StatsSummary } from '../../features/stats/stats.types';
import { toBars, toLinePoints, toProblemWords, toStatsSummary } from './stats-mapping';

const EMPTY_STATS: StatsApi = {
  summary: null,
  speed_series: [],
  helps_series: [],
  speed_by_style: [],
  speed_by_topic: [],
  problem_words: [],
  stretch_level_series: [],
  stretch_now: null,
};

/**
 * Wires `features/stats/` (the approved design) into the real `/stats`
 * route against `GET /api/stats` (issue #12) -- one read-only load, same
 * shape as `pages/history/history.ts`.
 */
@Component({
  selector: 'app-stats',
  imports: [...SUMI_LAYOUT, StatsScreen, SumiButtonDirective],
  templateUrl: './stats.html',
})
export class StatsPage {
  private readonly api = inject(Api);

  protected readonly loading = signal(true);
  /** The stats themselves could not be loaded at all -- T6, not a banner. */
  protected readonly failed = signal(false);
  protected readonly loadError = signal<string | null>(null);

  private readonly data = signal<StatsApi>(EMPTY_STATS);

  protected readonly summary = computed<StatsSummary | null>(() => {
    const summary = this.data().summary;
    return summary ? toStatsSummary(summary) : null;
  });
  protected readonly speedSeries = computed<readonly SumiLinePoint[]>(() =>
    toLinePoints(this.data().speed_series, 'speed'),
  );
  protected readonly helpsSeries = computed<readonly SumiLinePoint[]>(() =>
    toLinePoints(this.data().helps_series, 'helps'),
  );
  protected readonly speedByStyle = computed<readonly SumiBar[]>(() =>
    toBars(this.data().speed_by_style),
  );
  protected readonly speedByTopic = computed<readonly SumiBar[]>(() =>
    toBars(this.data().speed_by_topic),
  );
  protected readonly problemWords = computed<readonly ProblemWord[]>(() =>
    toProblemWords(this.data().problem_words),
  );
  protected readonly stretchLevelSeries = computed<readonly SumiLinePoint[]>(() =>
    toLinePoints(this.data().stretch_level_series, 'd'),
  );
  protected readonly stretchNow = computed<string | null>(() => this.data().stretch_now);

  constructor() {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.api.stats().then(
      (stats) => {
        this.loading.set(false);
        this.failed.set(false);
        this.loadError.set(null);
        this.data.set(stats);
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
}
