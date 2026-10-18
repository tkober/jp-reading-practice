import { Component, computed, input, output } from '@angular/core';
import { SumiCard, SumiHanko, SumiPage } from 'sumi-ui/layout';
import { SumiSessionGate, SumiSessionSummary, SumiSummaryTile } from 'sumi-ui/practice';
import { SumiDataTable, type SumiTableColumn, type SumiTableRow } from 'sumi-ui/charts';
import type { LookedUpWord } from './summary.types';

@Component({
  selector: 'app-summary-screen',
  templateUrl: './summary-screen.html',
  styleUrl: './summary-screen.scss',
  imports: [
    SumiPage,
    SumiCard,
    SumiHanko,
    SumiSessionGate,
    SumiSessionSummary,
    SumiSummaryTile,
    SumiDataTable,
  ],
  host: { class: 'app-summary-screen' },
})
export class SummaryScreen {
  readonly speedCharsPerMinute = input.required<number>();
  readonly helpsPerHundredWords = input.required<number>();
  readonly questionsCorrect = input.required<number>();
  readonly questionsTotal = input.required<number>();
  readonly activeTimeMs = input.required<number>();
  readonly lookedUpWords = input<readonly LookedUpWord[]>([]);
  /** "Stretch is now a little harder."/"...a little easier." (issue #13) --
   *  `null` hides the line entirely (not a stretch session, an overridden
   *  one, or "unchanged"). See `pages/read/stretch-note.ts`. */
  readonly stretchNote = input<string | null>(null);

  readonly readAgain = output<void>();
  readonly newText = output<void>();

  protected readonly tableColumns: readonly SumiTableColumn[] = [
    { key: 'word', label: 'Word' },
    { key: 'reading', label: 'Reading' },
    { key: 'meaning', label: 'Meaning' },
  ];

  protected readonly tableRows = computed<SumiTableRow[]>(() =>
    this.lookedUpWords().map((entry) => ({ ...entry })),
  );
}
