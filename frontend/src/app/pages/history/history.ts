import { Component } from '@angular/core';
import { SUMI_LAYOUT } from 'sumi-ui/layout';

/** Placeholder for the list of past reading sessions -- tracking arrives with a later issue. */
@Component({
  selector: 'app-history',
  imports: [...SUMI_LAYOUT],
  templateUrl: './history.html',
})
export class HistoryPage {}
