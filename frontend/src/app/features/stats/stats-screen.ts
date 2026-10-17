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
  readonly problemWords = input<readonly ProblemWord[]>([]);

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
