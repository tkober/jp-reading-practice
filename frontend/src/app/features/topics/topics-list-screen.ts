import { Component, input, output } from '@angular/core';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiBadge, SumiCard, SumiPage } from 'sumi-ui/layout';
import type { TopicSummary } from './topics.types';

@Component({
  selector: 'app-topics-list-screen',
  templateUrl: './topics-list-screen.html',
  styleUrl: './topics-list-screen.scss',
  imports: [SumiPage, SumiCard, SumiBadge, SumiButtonDirective],
  host: { class: 'app-topics-list-screen' },
})
export class TopicsListScreen {
  readonly topics = input.required<readonly TopicSummary[]>();

  readonly newTopic = output<void>();
  readonly editTopic = output<string>();
}
