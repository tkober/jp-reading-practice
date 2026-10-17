import { Component } from '@angular/core';
import { GeneratingScreen, type GenerationStep } from '../../features/read/generating/generating-screen';

const STEPS: readonly GenerationStep[] = [
  { label: 'Checking what you know', state: 'done' },
  { label: 'Writing the text', state: 'running' },
  { label: 'Measuring difficulty', state: 'pending' },
];

@Component({
  selector: 'preview-generating',
  template: `<app-generating-screen [steps]="steps" />`,
  imports: [GeneratingScreen],
})
export class GeneratingPreview {
  protected readonly steps = STEPS;
}
