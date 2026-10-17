import { Component, computed, input, output } from '@angular/core';
import { SumiSegmentedBar, type SumiSegment } from 'sumi-ui/charts';
import { SumiBanner } from 'sumi-ui/layout';
import { SumiSessionGate } from 'sumi-ui/practice';
import type { JlptShares } from '../setup/setup.types';

const JLPT_COLORS: Record<keyof JlptShares, string> = {
  n5: 'var(--sumi-seq-1)',
  n4: 'var(--sumi-seq-2)',
  n3: 'var(--sumi-seq-3)',
  n2: 'var(--sumi-seq-4)',
  n1: 'var(--sumi-seq-5)',
};

/** The reading gate: the generated text's measured values, shown before
 *  committing to read it. */
@Component({
  selector: 'app-gate-screen',
  templateUrl: './gate-screen.html',
  styleUrl: './gate-screen.scss',
  imports: [SumiSessionGate, SumiSegmentedBar, SumiBanner],
  host: { class: 'app-gate-screen' },
})
export class GateScreen {
  readonly titleJapanese = input.required<string>();
  readonly characterCount = input.required<number>();
  readonly estimatedMinutes = input.required<number>();
  readonly unknownKanjiPercent = input.required<number>();
  readonly jlptMix = input.required<JlptShares>();

  /** Set only when the generated text's `kanji_trainer_error` was set
   *  (issue #9's brief) -- generation still happened, just without the
   *  learner's own known set, so the gate says so instead of the measured
   *  values quietly meaning something different than usual. */
  readonly kanjiTrainerErrorNote = input<string | null>(null);

  readonly start = output<void>();

  protected readonly summaryLine = computed(
    () =>
      `${this.characterCount()} characters · ≈ ${this.estimatedMinutes()} min · ${this.unknownKanjiPercent()}% unknown kanji`,
  );

  protected readonly jlptSegments = computed<SumiSegment[]>(() => {
    const mix = this.jlptMix();
    return (Object.keys(mix) as (keyof JlptShares)[])
      .filter((level) => mix[level] > 0)
      .map((level) => ({
        label: level.toUpperCase(),
        value: mix[level],
        color: JLPT_COLORS[level],
      }));
  });
}
