import { Component } from '@angular/core';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

/** Placeholder for reading statistics (speed, help usage, level over time) -- a later issue. */
@Component({
  selector: 'app-stats',
  imports: [...SUMI_LAYOUT],
  templateUrl: './stats.html',
})
export class StatsPage {}
