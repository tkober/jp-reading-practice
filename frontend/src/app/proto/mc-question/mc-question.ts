// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// Four large tappable choice tiles for a multiple-choice comprehension
// question, with a settled correct/wrong state once answered. Sumi UI has
// `sumi-verdict` for the settled feedback line but nothing for the choice
// grid itself — the closest existing piece, `sumi-card[interactive]`, is a
// generic container with no selected/correct/wrong state of its own.
import { Component, computed, input, output } from '@angular/core';
import { SumiIcon } from 'sumi-ui/core';

export interface McOption {
  id: string;
  text: string;
}

const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F'];

@Component({
  selector: 'proto-mc-question',
  templateUrl: './mc-question.html',
  styleUrl: './mc-question.scss',
  imports: [SumiIcon],
  host: { class: 'proto-mc-question' },
})
export class McQuestion {
  readonly options = input.required<readonly McOption[]>();
  readonly selectedId = input<string | null>(null);
  /** Set once the question is answered — reveals correct/wrong styling and disables further taps. */
  readonly correctId = input<string | null>(null);

  readonly select = output<string>();

  protected readonly answered = computed(() => this.correctId() !== null);

  protected letterFor(index: number): string {
    return LETTERS[index] ?? String(index + 1);
  }

  protected toneFor(option: McOption): 'correct' | 'wrong' | 'neutral' {
    const correctId = this.correctId();
    if (correctId === null) {
      return 'neutral';
    }
    if (option.id === correctId) {
      return 'correct';
    }
    if (option.id === this.selectedId()) {
      return 'wrong';
    }
    return 'neutral';
  }

  protected onSelect(id: string): void {
    if (this.answered()) {
      return;
    }
    this.select.emit(id);
  }
}
