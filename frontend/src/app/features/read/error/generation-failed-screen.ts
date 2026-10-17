import { Component, input, output } from '@angular/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiErrorState } from 'sumi-ui/layout';

/** T6-style full-screen error (see `sumi-error-state`'s own doc comment)
 *  for a generation that failed outright — not a banner, since there is no
 *  partial page behind it worth keeping visible yet. */
@Component({
  selector: 'app-generation-failed-screen',
  templateUrl: './generation-failed-screen.html',
  imports: [SumiErrorState, SumiButtonDirective],
  host: { class: 'app-generation-failed-screen' },
})
export class GenerationFailedScreen {
  readonly message = input("The text could not be generated. The model didn't respond in time.");

  readonly retry = output<void>();
  readonly backToSetup = output<void>();
}
