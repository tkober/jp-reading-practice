import { Component } from '@angular/core';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

/**
 * Placeholder for the reading screen -- text generation and the reading view
 * itself arrive with a later issue (see REQUIREMENTS.md). This is the
 * default route (`app.routes.ts`).
 */
@Component({
  selector: 'app-read',
  imports: [...SUMI_LAYOUT],
  templateUrl: './read.html',
})
export class ReadPage {}
