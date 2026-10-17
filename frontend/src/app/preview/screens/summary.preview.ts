import { Component } from '@angular/core';
import { SummaryScreen } from '../../features/read/summary/summary-screen';
import type { LookedUpWord } from '../../features/read/summary/summary.types';

const LOOKED_UP_WORDS: readonly LookedUpWord[] = [
  { word: '兼六園', reading: 'けんろくえん', meaning: 'Kenrokuen (garden)' },
  { word: '治部煮', reading: 'じぶに', meaning: 'jibuni (a Kanazawa dish)' },
  { word: '九谷焼', reading: 'くたにやき', meaning: 'Kutani ware (pottery)' },
];

@Component({
  selector: 'preview-summary',
  template: `
    <app-summary-screen
      [speedCharsPerMinute]="137"
      [helpsPerHundredWords]="10"
      [questionsCorrect]="2"
      [questionsTotal]="3"
      [activeTimeMs]="252000"
      [lookedUpWords]="lookedUpWords"
    />
  `,
  imports: [SummaryScreen],
})
export class SummaryPreview {
  protected readonly lookedUpWords = LOOKED_UP_WORDS;
}
