import { Component, computed, input } from '@angular/core';
import {
  SumiBarChart,
  SumiDataTable,
  SumiLineChart,
  SumiStatGrid,
  SumiStatTile,
  type SumiBar,
  type SumiLinePoint,
  type SumiTableColumn,
  type SumiTableRow,
} from 'sumi-ui/charts';
import { SumiEmptyState, SumiPage } from 'sumi-ui/layout';
import type { ProblemWord, StatsSummary } from './stats.types';

@Component({
  selector: 'app-stats-screen',
  templateUrl: './stats-screen.html',
  styleUrl: './stats-screen.scss',
  imports: [
    SumiPage,
    SumiEmptyState,
    SumiStatGrid,
    SumiStatTile,
    SumiLineChart,
    SumiBarChart,
    SumiDataTable,
  ],
  host: { class: 'app-stats-screen' },
})
export class StatsScreen {
  /** `null` — fewer than 3 sessions so far, see `sumi-empty-state` below. */
  readonly summary = input<StatsSummary | null>(null);
  readonly speedSeries = input<readonly SumiLinePoint[]>([]);
  readonly helpsSeries = input<readonly SumiLinePoint[]>([]);
  readonly speedByStyle = input<readonly SumiBar[]>([]);
  /** Median 字/min per topic (issue #12), a second bar chart under "Speed
   *  by style" -- same shape, grouped by topic instead. */
  readonly speedByTopic = input<readonly SumiBar[]>([]);
  readonly problemWords = input<readonly ProblemWord[]>([]);
  /** `d_after` over Stretch's adjustments, oldest first (issue #13) --
   *  empty hides the whole "Stretch level" section, same convention as
   *  every other Stats section being empty under `summary() === null`. */
  readonly stretchLevelSeries = input<readonly SumiLinePoint[]>([]);
  /** "Now: N5 45 · N4 35 · N3 18 · N2 2 · 5.5 % unknown kanji" -- `null`
   *  alongside `stretchLevelSeries` being empty. */
  readonly stretchNow = input<string | null>(null);

  protected readonly problemWordsColumns: readonly SumiTableColumn[] = [
    { key: 'word', label: 'Word' },
    { key: 'reading', label: 'Reading' },
    { key: 'meaning', label: 'Meaning' },
    { key: 'timesLookedUp', label: 'Looked up', align: 'end' },
  ];

  protected readonly problemWordsRows = computed<SumiTableRow[]>(() =>
    this.problemWords().map((word) => ({ ...word })),
  );
}
