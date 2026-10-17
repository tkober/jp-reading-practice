import { Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { SumiIcon } from 'sumi-ui/core';
import {
  SumiButtonDirective,
  SumiSegmentedControl,
  SumiSliderDirective,
  type SumiSegmentedOption,
} from 'sumi-ui/forms';
import { SumiBanner, SumiCard, SumiPage } from 'sumi-ui/layout';
import {
  JlptMultiSlider,
  type JlptShares,
} from '../../../proto/jlpt-multi-slider/jlpt-multi-slider';
import { TopicTilePicker, type TopicTileOption } from '../../../proto/topic-tile-picker/topic-tile-picker';
import {
  READING_LENGTH_CHARS,
  READING_LENGTH_LABELS,
  summarizeDifficulty,
  type DifficultyPreset,
  type ReadingLength,
  type TextStyle,
} from './setup.types';

const LENGTH_OPTIONS: SumiSegmentedOption<ReadingLength>[] = (
  Object.keys(READING_LENGTH_LABELS) as ReadingLength[]
).map((length) => ({ value: length, label: READING_LENGTH_LABELS[length] }));

const PRESET_OPTIONS: SumiSegmentedOption<DifficultyPreset>[] = [
  { value: 'easy', label: 'Easy' },
  { value: 'stretch', label: 'Stretch' },
  { value: 'challenge', label: 'Challenge' },
];

const STYLE_OPTIONS: SumiSegmentedOption<TextStyle>[] = [
  { value: 'casual', label: 'Casual' },
  { value: 'polite', label: 'Polite' },
  { value: 'formal', label: 'Formal' },
];

/**
 * The "Read" setup screen: topic, length, difficulty and (collapsed by
 * default) the fine controls behind it. Fully controlled by its inputs —
 * the page that hosts it (#9+) owns the actual selection state.
 */
@Component({
  selector: 'app-setup-screen',
  templateUrl: './setup-screen.html',
  styleUrl: './setup-screen.scss',
  imports: [
    RouterLink,
    SumiIcon,
    SumiButtonDirective,
    SumiSegmentedControl,
    SumiSliderDirective,
    SumiBanner,
    SumiCard,
    SumiPage,
    JlptMultiSlider,
    TopicTilePicker,
  ],
  host: { class: 'app-setup-screen' },
})
export class SetupScreen {
  readonly topics = input.required<readonly TopicTileOption[]>();
  readonly selectedTopicId = input<string | null>(null);

  readonly length = input<ReadingLength>('medium');
  readonly readingSpeedCharsPerMinute = input(152);

  readonly preset = input<DifficultyPreset>('stretch');
  readonly unknownKanjiSharePercent = input(5);
  readonly jlptMix = input.required<JlptShares>();
  readonly style = input<TextStyle>('polite');
  readonly adjustOpen = input(false);

  readonly hasOpenAiKey = input(true);
  readonly kanjiTrainerOnline = input(true);

  readonly topicSelect = output<string>();
  readonly lengthChange = output<ReadingLength>();
  readonly presetChange = output<DifficultyPreset>();
  readonly unknownKanjiShareChange = output<number>();
  readonly jlptMixChange = output<JlptShares>();
  readonly styleChange = output<TextStyle>();
  readonly adjustToggle = output<void>();
  readonly generate = output<void>();

  protected readonly lengthOptions = LENGTH_OPTIONS;
  protected readonly presetOptions = PRESET_OPTIONS;
  protected readonly styleOptions = STYLE_OPTIONS;

  protected readonly estimateText = computed(() => {
    const chars = READING_LENGTH_CHARS[this.length()];
    const minutes = Math.max(1, Math.round(chars / this.readingSpeedCharsPerMinute()));
    return `≈ ${minutes} min at your pace (${this.readingSpeedCharsPerMinute()} 字/min)`;
  });

  protected readonly difficultySummary = computed(() =>
    summarizeDifficulty({
      unknownKanjiSharePercent: this.unknownKanjiSharePercent(),
      jlptMix: this.jlptMix(),
      style: this.style(),
    }),
  );

  protected readonly canGenerate = computed(() => this.hasOpenAiKey());

  protected onGenerate(): void {
    if (!this.canGenerate()) {
      return;
    }
    this.generate.emit();
  }
}
