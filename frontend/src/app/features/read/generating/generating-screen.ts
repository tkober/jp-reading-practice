import { Component, input } from '@angular/core';
import { SumiIcon } from 'sumi-ui/core';
import { SumiSessionGate } from 'sumi-ui/practice';

export type GenerationStepState = 'done' | 'running' | 'pending';

export interface GenerationStep {
  label: string;
  state: GenerationStepState;
}

/** The session gate shown while a text is being generated: three steps with
 *  their own state, no action (there is nothing to start yet). */
@Component({
  selector: 'app-generating-screen',
  templateUrl: './generating-screen.html',
  styleUrl: './generating-screen.scss',
  imports: [SumiIcon, SumiSessionGate],
  host: { class: 'app-generating-screen' },
})
export class GeneratingScreen {
  readonly steps = input.required<readonly GenerationStep[]>();
}
