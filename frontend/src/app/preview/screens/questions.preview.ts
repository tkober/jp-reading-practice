import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { QuestionsScreen } from '../../features/read/questions/questions-screen';
import { COMPREHENSION_QUESTIONS } from '../fixtures/reading-text.fixture';

export type QuestionsPreviewVariant = 'default' | 'answered';

@Component({
  selector: 'preview-questions',
  template: `
    <app-questions-screen
      [question]="question"
      [questionNumber]="2"
      [totalQuestions]="3"
      [selectedOptionId]="selectedOptionId()"
      [answered]="answered()"
      (select)="onSelect($event)"
      (next)="next.set(true)"
    />
    @if (next()) {
      <p class="preview-note">→ would advance to the next question (or /preview/summary)</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [QuestionsScreen],
})
export class QuestionsPreview {
  protected readonly question = COMPREHENSION_QUESTIONS[1];
  protected readonly selectedOptionId = signal<string | null>(null);
  protected readonly answered = signal(false);
  protected readonly next = signal(false);

  constructor() {
    const variant = (inject(ActivatedRoute).snapshot.data['variant'] ?? 'default') as QuestionsPreviewVariant;
    if (variant === 'answered') {
      this.selectedOptionId.set('q2a');
      this.answered.set(true);
    }
  }

  protected onSelect(optionId: string): void {
    this.selectedOptionId.set(optionId);
    this.answered.set(true);
  }
}
