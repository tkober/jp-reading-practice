import { Component } from '@angular/core';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

/** Placeholder for the preset-topics list that text generation picks from -- a later issue. */
@Component({
  selector: 'app-topics',
  imports: [...SUMI_LAYOUT],
  templateUrl: './topics.html',
})
export class TopicsPage {}
