import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { SetupScreen } from '../../features/read/setup/setup-screen';
import {
  DIFFICULTY_PRESETS,
  type DifficultyPreset,
  type ReadingLength,
  type TextStyle,
} from '../../features/read/setup/setup.types';
import { DEFAULT_JLPT_MIX, TOPIC_TILES } from '../fixtures/topics.fixture';
import type { JlptShares } from '../../proto/jlpt-multi-slider/jlpt-multi-slider';

/** One component behind four routes (`setup`, `setup-adjust`,
 *  `setup-no-key`, `setup-kt-offline`) — the only difference between them
 *  is the initial state, set from the route's `data.variant` so the preview
 *  index can link each state directly. */
export type SetupPreviewVariant = 'default' | 'adjust' | 'no-key' | 'kt-offline';

@Component({
  selector: 'preview-setup',
  template: `
    <app-setup-screen
      [topics]="topics"
      [selectedTopicId]="selectedTopicId()"
      [length]="length()"
      [preset]="preset()"
      [unknownKanjiSharePercent]="unknownKanjiSharePercent()"
      [jlptMix]="jlptMix()"
      [style]="style()"
      [adjustOpen]="adjustOpen()"
      [hasOpenAiKey]="hasOpenAiKey()"
      [kanjiTrainerOnline]="kanjiTrainerOnline()"
      (topicSelect)="selectedTopicId.set($event)"
      (lengthChange)="length.set($event)"
      (presetChange)="onPresetChange($event)"
      (unknownKanjiShareChange)="unknownKanjiSharePercent.set($event)"
      (jlptMixChange)="jlptMix.set($event)"
      (styleChange)="style.set($event)"
      (adjustToggle)="adjustOpen.set(!adjustOpen())"
      (generate)="generated.set(true)"
    />
    @if (generated()) {
      <p class="preview-note">→ would navigate to /preview/generating</p>
    }
  `,
  styles: ['.preview-note { margin: var(--sumi-space-3) var(--sumi-space-4); color: var(--sumi-accent-ink); font-size: var(--sumi-text-sm); }'],
  imports: [SetupScreen],
})
export class SetupPreview {
  protected readonly topics = TOPIC_TILES;

  protected readonly selectedTopicId = signal<string | null>('travel');
  protected readonly length = signal<ReadingLength>('medium');
  protected readonly preset = signal<DifficultyPreset>('stretch');
  protected readonly unknownKanjiSharePercent = signal(DIFFICULTY_PRESETS.stretch.unknownKanjiSharePercent);
  protected readonly jlptMix = signal<JlptShares>(DEFAULT_JLPT_MIX);
  protected readonly style = signal<TextStyle>('polite');
  protected readonly adjustOpen = signal(false);
  protected readonly hasOpenAiKey = signal(true);
  protected readonly kanjiTrainerOnline = signal(true);
  protected readonly generated = signal(false);

  constructor() {
    const variant = (inject(ActivatedRoute).snapshot.data['variant'] ?? 'default') as SetupPreviewVariant;
    if (variant === 'adjust') {
      this.adjustOpen.set(true);
    } else if (variant === 'no-key') {
      this.hasOpenAiKey.set(false);
    } else if (variant === 'kt-offline') {
      this.kanjiTrainerOnline.set(false);
    }
  }

  protected onPresetChange(preset: DifficultyPreset): void {
    this.preset.set(preset);
    const settings = DIFFICULTY_PRESETS[preset];
    this.unknownKanjiSharePercent.set(settings.unknownKanjiSharePercent);
    this.jlptMix.set(settings.jlptMix);
    this.style.set(settings.style);
  }
}
