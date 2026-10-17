import { Component, computed, input, output } from '@angular/core';
import { SumiDataTable, type SumiTableColumn, type SumiTableRow } from 'sumi-ui/charts';
import { SumiEmptyState, SumiPage } from 'sumi-ui/layout';
import type { HistorySession } from './history.types';

@Component({
  selector: 'app-history-screen',
  templateUrl: './history-screen.html',
  styleUrl: './history-screen.scss',
  imports: [SumiPage, SumiEmptyState, SumiDataTable],
  host: { class: 'app-history-screen' },
})
export class HistoryScreen {
  readonly sessions = input<readonly HistorySession[]>([]);

  readonly openSession = output<string>();

  protected readonly columns: readonly SumiTableColumn[] = [
    { key: 'date', label: 'Date' },
    { key: 'title', label: 'Title' },
    { key: 'topic', label: 'Topic' },
    { key: 'length', label: 'Length' },
    { key: 'speed', label: '字/min', align: 'end' },
    { key: 'helps', label: 'Helps/100', align: 'end' },
    { key: 'score', label: 'Score', align: 'end' },
  ];

  // Newest first, regardless of what order the input happens to arrive in —
  // the natural reading order for a history list.
  protected readonly rows = computed<SumiTableRow[]>(() =>
    [...this.sessions()].reverse().map((session) => ({
      id: session.id,
      date: session.date,
      title: session.titleJapanese,
      topic: session.topicName,
      length: session.length,
      speed: session.speedCharsPerMinute,
      helps: session.helpsPerHundred,
      score: `${session.scoreCorrect}/${session.scoreTotal}`,
    })),
  );

  protected onRowActivate(row: SumiTableRow): void {
    this.openSession.emit(row['id'] as string);
  }
}
