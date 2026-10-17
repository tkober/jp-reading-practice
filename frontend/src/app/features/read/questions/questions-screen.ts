import { Component, computed, input, output } from '@angular/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiPage, SumiProgress } from 'sumi-ui/layout';
import { SumiVerdictCard } from 'sumi-ui/practice';
import { McQuestion } from '../../../proto/mc-question/mc-question';
import type { ComprehensionQuestion } from './questions.types';

/**
 * One comprehension question at a time: four choice tiles, a progress
 * line, and — once answered — a `sumi-verdict` with the right answer.
 * Mandatory after every generated text (2-3 questions, see the concept).
 */
@Component({
  selector: 'app-questions-screen',
  templateUrl: './questions-screen.html',
  styleUrl: './questions-screen.scss',
  imports: [SumiPage, SumiProgress, SumiVerdictCard, McQuestion, SumiButtonDirective],
  host: { class: 'app-questions-screen' },
})
export class QuestionsScreen {
  readonly question = input.required<ComprehensionQuestion>();
  readonly questionNumber = input.required<number>();
  readonly totalQuestions = input.required<number>();
  readonly selectedOptionId = input<string | null>(null);
  readonly answered = input(false);

  readonly select = output<string>();
  readonly next = output<void>();

  protected readonly correctOptionId = computed(() =>
    this.answered() ? this.question().correctOptionId : null,
  );

  protected readonly verdictKind = computed<'correct' | 'wrong'>(() =>
    this.selectedOptionId() === this.question().correctOptionId ? 'correct' : 'wrong',
  );

  protected readonly correctOptionText = computed(
    () => this.question().options.find((option) => option.id === this.question().correctOptionId)?.text ?? '',
  );

  /** Only a wrong answer needs to be told what the right one was — a
   *  correct answer already says "Correct", repeating it adds nothing. */
  protected readonly verdictMessage = computed(() =>
    this.verdictKind() === 'wrong' ? `Correct answer: ${this.correctOptionText()}` : undefined,
  );
}
