import { Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { SuggestionApi } from '../../../core/api.types';
import { SumiIcon } from 'sumi-ui/core';
import {
  SumiButtonDirective,
  SumiSegmentedControl,
  SumiShareSlider,
  SumiSliderDirective,
  SumiTilePicker,
  type SumiSegmentedOption,
  type SumiShareSegment,
  type SumiTileOption,
} from 'sumi-ui/forms';
import { SumiBanner, SumiCard, SumiPage } from 'sumi-ui/layout';
import { applySuggestionToSetup } from './suggestion-apply';
import {
  READING_LENGTH_CHARS,
  READING_LENGTH_LABELS,
  jlptSharesToSegments,
  segmentsToJlptShares,
  summarizeDifficulty,
  type DifficultyPreset,
  type JlptShares,
  type ReadingLength,
  type TextStyle,
} from './setup.types';

/** Display order/labels for the suggestion card's overrides line -- same
 *  levels `setup.types.ts`'s own (private) `JLPT_ORDER`/`JLPT_LABELS` use,
 *  kept local here since nothing else in this component needs them. */
const SUGGESTION_JLPT_ORDER: (keyof JlptShares)[] = ['n5', 'n4', 'n3', 'n2', 'n1'];
const SUGGESTION_JLPT_LABELS: Record<keyof JlptShares, string> = {
  n5: 'N5',
  n4: 'N4',
  n3: 'N3',
  n2: 'N2',
  n1: 'N1',
};

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
    SumiTilePicker,
    SumiShareSlider,
  ],
  host: { class: 'app-setup-screen' },
})
export class SetupScreen {
  /** Includes the "Surprise me" tile (`special: true`) as a normal option
   *  — `sumi-tile-picker` (sumi-ui#98) has no dedicated slot for it the
   *  way `proto/topic-tile-picker`'s own `surpriseId` input did, so the
   *  host supplies it as part of the list, same as every other tile. */
  readonly topics = input.required<readonly SumiTileOption<string>[]>();
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

  /** "Suggest next text" (issue #14) -- `suggesting` disables the button
   *  and shows "Thinking…" in the card's place; `suggestion`/
   *  `suggestionError` are mutually exclusive with each other and with
   *  `suggesting`, all controlled by the host page. */
  readonly suggesting = input(false);
  readonly suggestion = input<SuggestionApi | null>(null);
  readonly suggestionError = input<string | null>(null);

  readonly topicSelect = output<string>();
  readonly lengthChange = output<ReadingLength>();
  readonly presetChange = output<DifficultyPreset>();
  readonly unknownKanjiShareChange = output<number>();
  readonly jlptMixChange = output<JlptShares>();
  readonly styleChange = output<TextStyle>();
  readonly adjustToggle = output<void>();
  readonly generate = output<void>();
  readonly suggestNext = output<void>();
  readonly useSuggestion = output<void>();
  readonly dismissSuggestion = output<void>();

  protected readonly lengthOptions = LENGTH_OPTIONS;
  protected readonly presetOptions = PRESET_OPTIONS;
  protected readonly styleOptions = STYLE_OPTIONS;

  /** `sumi-tile-picker`'s `options` wants a mutable array; `topics()` stays
   *  `readonly` for every other consumer, so this copies rather than
   *  loosening the input's own type. */
  protected readonly tileOptions = computed<SumiTileOption<string>[]>(() => [...this.topics()]);

  /** `sumi-share-slider`'s own shape — see `setup.types.ts`'s conversion
   *  helpers for why this app keeps the keyed `JlptShares` everywhere else. */
  protected readonly jlptSegments = computed<SumiShareSegment[]>(() =>
    jlptSharesToSegments(this.jlptMix()),
  );

  protected onJlptSegmentsChange(segments: SumiShareSegment[]): void {
    this.jlptMixChange.emit(segmentsToJlptShares(segments));
  }

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

  // --- "Suggest next text" card (issue #14) -------------------------------

  /** The suggested topic's own tile (for its glyph/title) -- `null` while
   *  the topics list has not loaded yet, or for a stale suggestion whose
   *  topic no longer exists. */
  protected readonly suggestionTopicTile = computed<SumiTileOption<string> | null>(() => {
    const current = this.suggestion();
    if (!current) {
      return null;
    }
    return this.tileOptions().find((tile) => tile.value === current.topic_slug) ?? null;
  });

  protected readonly suggestionLengthLabel = computed(() => {
    const current = this.suggestion();
    return current ? READING_LENGTH_LABELS[current.length] : '';
  });

  protected readonly suggestionPresetLabel = computed(() => {
    const current = this.suggestion();
    if (!current) {
      return '';
    }
    return (
      this.presetOptions.find((option) => option.value === current.preset)?.label ?? current.preset
    );
  });

  /** The suggested overrides converted to the same percent shapes the
   *  setup controls use (`applySuggestionToSetup`) -- reused here purely
   *  for display, so the card's one-line summary and what "Use this"
   *  actually applies can never drift apart. */
  protected readonly suggestionApplied = computed(() => {
    const current = this.suggestion();
    return current ? applySuggestionToSetup(current) : null;
  });

  /** "casual · 8% unknown kanji · N5 60% N4 40%" -- `null` when the
   *  suggestion has no overrides at all (the common case), so the card
   *  shows only length/preset. */
  protected readonly suggestionOverridesLine = computed<string | null>(() => {
    const applied = this.suggestionApplied();
    if (!applied?.adjustOpen) {
      return null;
    }
    const parts: string[] = [];
    if (applied.style) {
      parts.push(applied.style);
    }
    if (applied.unknownKanjiSharePercent !== undefined) {
      parts.push(`${applied.unknownKanjiSharePercent}% unknown kanji`);
    }
    if (applied.jlptMix) {
      const mix = applied.jlptMix;
      const mixParts = SUGGESTION_JLPT_ORDER.filter((level) => mix[level] > 0).map(
        (level) => `${SUGGESTION_JLPT_LABELS[level]} ${mix[level]}%`,
      );
      if (mixParts.length > 0) {
        parts.push(mixParts.join(' '));
      }
    }
    return parts.length > 0 ? parts.join(' · ') : null;
  });
}
