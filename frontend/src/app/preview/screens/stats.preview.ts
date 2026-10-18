import { Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { StatsScreen } from '../../features/stats/stats-screen';
import {
  HELPS_SERIES,
  PROBLEM_WORDS,
  SPEED_BY_STYLE,
  SPEED_BY_TOPIC,
  SPEED_SERIES,
  STATS_SUMMARY,
} from '../fixtures/stats.fixture';
import type { StatsSummary } from '../../features/stats/stats.types';

export type StatsPreviewVariant = 'default' | 'empty';

@Component({
  selector: 'preview-stats',
  template: `
    <app-stats-screen
      [summary]="summary"
      [speedSeries]="speedSeries"
      [helpsSeries]="helpsSeries"
      [speedByStyle]="speedByStyle"
      [speedByTopic]="speedByTopic"
      [problemWords]="problemWords"
    />
  `,
  imports: [StatsScreen],
})
export class StatsPreview {
  protected summary: StatsSummary | null = STATS_SUMMARY;
  protected speedSeries = SPEED_SERIES;
  protected speedByStyle = SPEED_BY_STYLE;
  protected speedByTopic = SPEED_BY_TOPIC;
  protected helpsSeries = HELPS_SERIES;
  protected problemWords = PROBLEM_WORDS;

  constructor() {
    const variant = (inject(ActivatedRoute).snapshot.data['variant'] ??
      'default') as StatsPreviewVariant;
    if (variant === 'empty') {
      this.summary = null;
      this.speedSeries = [];
      this.helpsSeries = [];
      this.speedByStyle = [];
      this.speedByTopic = [];
      this.problemWords = [];
    }
  }
}
