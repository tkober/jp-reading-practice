import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import type { SumiTileOption } from 'sumi-ui/forms';

import { Api, ApiError, KanjiTrainerStatusUnavailable } from '../../core/api';
import type {
  PresetsApi,
  SuggestionApi,
  TextCreatePayload,
  TextOutApi,
  TextOverridesApi,
} from '../../core/api.types';
import { GenerationFailedScreen } from '../../features/read/error/generation-failed-screen';
import {
  GeneratingScreen,
  type GenerationStep,
} from '../../features/read/generating/generating-screen';
import { GateScreen } from '../../features/read/gate/gate-screen';
import { SetupScreen } from '../../features/read/setup/setup-screen';
import {
  DIFFICULTY_PRESETS,
  type DifficultyPreset,
  type DifficultySettings,
  type JlptShares,
  type ReadingLength,
  type TextStyle,
} from '../../features/read/setup/setup.types';
import { applySuggestionToSetup } from '../../features/read/setup/suggestion-apply';

type ReadPageState = 'setup' | 'generating' | 'gate' | 'error';

const STORAGE_KEY = 'jp-reading-practice:setup';

interface StoredSetup {
  topicId?: string | null;
  length?: ReadingLength;
  preset?: DifficultyPreset;
  unknownKanjiSharePercent?: number;
  jlptMix?: JlptShares;
  style?: TextStyle;
  touched?: { style?: boolean; kanji?: boolean; jlpt?: boolean };
}

const INITIAL_STEPS: readonly GenerationStep[] = [
  { label: 'Reading your level', state: 'done' },
  { label: 'Writing the text', state: 'running' },
  { label: 'Checking it against your level', state: 'pending' },
];

/**
 * `/read`: setup, generating, the gate, and a failed-generation error --
 * everything before a session exists (issue #9). Once the gate's "Start"
 * creates a session, the page navigates to `/read/:sessionId`
 * (`ReadSessionPage`), which owns the reading/questions/summary states
 * instead.
 */
@Component({
  selector: 'app-read',
  templateUrl: './read.html',
  imports: [SetupScreen, GeneratingScreen, GateScreen, GenerationFailedScreen],
})
export class ReadPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  protected readonly state = signal<ReadPageState>('setup');

  protected readonly topics = signal<readonly SumiTileOption<string>[]>([]);
  protected readonly selectedTopicId = signal<string | null>(null);
  protected readonly length = signal<ReadingLength>('medium');
  protected readonly preset = signal<DifficultyPreset>('stretch');
  protected readonly unknownKanjiSharePercent = signal(
    DIFFICULTY_PRESETS['stretch'].unknownKanjiSharePercent,
  );
  protected readonly jlptMix = signal<JlptShares>(DIFFICULTY_PRESETS['stretch'].jlptMix);
  protected readonly style = signal<TextStyle>(DIFFICULTY_PRESETS['stretch'].style);
  protected readonly adjustOpen = signal(false);

  /**
   * Only true once the learner actually changes a control inside "Adjust"
   * -- gates whether that one field is sent as an override at all, so a
   * preset chosen and left alone sends no `overrides`, and the backend's
   * own preset (and the topic's own `default_style`) apply untouched.
   * See `setup.types.ts`'s `DIFFICULTY_PRESETS` doc comment.
   */
  private readonly styleTouched = signal(false);
  private readonly kanjiTouched = signal(false);
  private readonly jlptTouched = signal(false);

  protected readonly hasOpenAiKey = signal(true);
  protected readonly kanjiTrainerOnline = signal(true);
  protected readonly paceCharsPerMinute = signal(150);

  /**
   * `GET /api/presets`'s resolved values (issue #13) -- `null` until it
   * loads, or if it never does (offline), in which case `effectiveDefaults`
   * falls back to the static `DIFFICULTY_PRESETS` table below, exactly as
   * before #13.
   */
  private readonly presets = signal<PresetsApi | null>(null);

  protected readonly generationSteps = signal<readonly GenerationStep[]>(INITIAL_STEPS);
  protected readonly errorMessage = signal('');
  protected readonly textOut = signal<TextOutApi | null>(null);

  // --- "Suggest next text" (issue #14) ------------------------------------

  protected readonly suggesting = signal(false);
  protected readonly suggestion = signal<SuggestionApi | null>(null);
  protected readonly suggestionError = signal<string | null>(null);

  /**
   * The suggestion "Use this" last applied, as long as topic/length/preset
   * still match it exactly -- cleared the moment any of those three is
   * changed by hand (brief: "a learner who changed things did not 'use'
   * it"). Sent as `suggestion_id` on the next `POST /api/texts`; the
   * backend re-checks the same match before marking it used, so this is
   * never the only guard.
   */
  private readonly appliedSuggestionId = signal<number | null>(null);

  private lastPayload: TextCreatePayload | null = null;

  constructor() {
    this.restoreSetup();

    this.api.topics().then(
      (topics) => {
        this.topics.set([
          ...topics.map((topic) => ({
            value: topic.slug,
            glyph: topic.glyph,
            label: topic.title,
            lang: 'ja' as const,
          })),
          { value: 'surprise', glyph: '✨', label: 'Surprise me', special: true },
        ]);
      },
      () => undefined, // The tile picker just stays empty; not worth a T6 for this screen.
    );

    this.api.settings().then(
      (settings) => this.hasOpenAiKey.set(settings.openai_api_key_set),
      () => undefined,
    );

    this.api.kanjiTrainerStatus().then(
      (status) => this.kanjiTrainerOnline.set(status.reachable),
      (error: unknown) => {
        // A backend predating issue #5 (404) means nothing to report here
        // either way -- leave the default (no banner) rather than imply an
        // outage that may not exist.
        if (!(error instanceof KanjiTrainerStatusUnavailable)) {
          this.kanjiTrainerOnline.set(true);
        }
      },
    );

    this.api.readingPace().then(
      (pace) => this.paceCharsPerMinute.set(pace.chars_per_minute),
      () => undefined, // Falls back to the component's own 150 default.
    );

    this.api.presets().then(
      (presets) => {
        this.presets.set(presets);
        // Refresh the *currently selected* preset's defaults now that the
        // live numbers are in -- but only for a field the learner has not
        // touched themselves (the same condition `onPresetChange` applies).
        if (!this.kanjiTouched()) {
          this.unknownKanjiSharePercent.set(
            this.effectiveDefaults(this.preset()).unknownKanjiSharePercent,
          );
        }
        if (!this.jlptTouched()) {
          this.jlptMix.set(this.effectiveDefaults(this.preset()).jlptMix);
        }
      },
      () => undefined, // Offline -- the static DIFFICULTY_PRESETS stays the fallback.
    );
  }

  /**
   * A preset's resolved defaults: the live `GET /api/presets` numbers once
   * loaded (`unknown_kanji_target`/`jlpt_mix` as percent, matching
   * `DifficultySettings`'s own shape), else the static fallback table --
   * `style` always comes from the static table, since no preset on the
   * backend carries one of its own (`presets.Preset.style_default` is
   * `None` for all three; the *topic's* own default wins instead).
   */
  private effectiveDefaults(preset: DifficultyPreset): DifficultySettings {
    const fallback = DIFFICULTY_PRESETS[preset];
    const live = this.presets();
    if (!live) {
      return fallback;
    }
    const resolved = live[preset];
    return {
      unknownKanjiSharePercent: Math.round(resolved.unknown_kanji_target * 100),
      jlptMix: {
        n5: Math.round((resolved.jlpt_mix.n5 ?? 0) * 100),
        n4: Math.round((resolved.jlpt_mix.n4 ?? 0) * 100),
        n3: Math.round((resolved.jlpt_mix.n3 ?? 0) * 100),
        n2: Math.round((resolved.jlpt_mix.n2 ?? 0) * 100),
        n1: Math.round((resolved.jlpt_mix.n1 ?? 0) * 100),
      },
      style: fallback.style,
    };
  }

  // --- setup -----------------------------------------------------------

  protected onTopicSelect(topicId: string): void {
    this.selectedTopicId.set(topicId);
    this.appliedSuggestionId.set(null);
    this.persistSetup();
  }

  protected onLengthChange(length: ReadingLength): void {
    this.length.set(length);
    this.appliedSuggestionId.set(null);
    this.persistSetup();
  }

  protected onPresetChange(preset: DifficultyPreset): void {
    this.preset.set(preset);
    const defaults = this.effectiveDefaults(preset);
    this.unknownKanjiSharePercent.set(defaults.unknownKanjiSharePercent);
    this.jlptMix.set(defaults.jlptMix);
    this.style.set(defaults.style);
    this.styleTouched.set(false);
    this.kanjiTouched.set(false);
    this.jlptTouched.set(false);
    this.appliedSuggestionId.set(null);
    this.persistSetup();
  }

  protected onUnknownKanjiShareChange(percent: number): void {
    this.unknownKanjiSharePercent.set(percent);
    this.kanjiTouched.set(true);
    this.persistSetup();
  }

  protected onJlptMixChange(mix: JlptShares): void {
    this.jlptMix.set(mix);
    this.jlptTouched.set(true);
    this.persistSetup();
  }

  protected onStyleChange(style: TextStyle): void {
    this.style.set(style);
    this.styleTouched.set(true);
    this.persistSetup();
  }

  protected onAdjustToggle(): void {
    this.adjustOpen.set(!this.adjustOpen());
  }

  protected onGenerate(): void {
    const topicSlug = this.selectedTopicId();
    if (!topicSlug) {
      return;
    }

    const payload: TextCreatePayload = {
      topic_slug: topicSlug,
      length: this.length(),
      preset: this.preset(),
    };

    const overrides: TextOverridesApi = {};
    if (this.styleTouched()) {
      overrides.style = this.style();
    }
    if (this.kanjiTouched()) {
      overrides.unknown_kanji_target = this.unknownKanjiSharePercent() / 100;
    }
    if (this.jlptTouched()) {
      const mix = this.jlptMix();
      overrides.jlpt_mix = {
        n5: mix.n5 / 100,
        n4: mix.n4 / 100,
        n3: mix.n3 / 100,
        n2: mix.n2 / 100,
        n1: mix.n1 / 100,
      };
    }
    if (Object.keys(overrides).length > 0) {
      payload.overrides = overrides;
    }
    const suggestionId = this.appliedSuggestionId();
    if (suggestionId !== null) {
      payload.suggestion_id = suggestionId;
    }

    this.lastPayload = payload;
    this.runGeneration(payload);
  }

  // --- "Suggest next text" (issue #14) ------------------------------------

  protected onSuggestNext(): void {
    this.suggesting.set(true);
    this.suggestionError.set(null);
    this.suggestion.set(null);

    this.api.suggestNext().then(
      (suggestion) => {
        this.suggesting.set(false);
        this.suggestion.set(suggestion);
      },
      (error: unknown) => {
        this.suggesting.set(false);
        this.suggestionError.set(
          error instanceof Error ? error.message : 'The suggestion could not be generated.',
        );
      },
    );
  }

  /**
   * Applies the suggestion to the setup controls -- never generates
   * anything itself (brief). Dismisses the card the same way "Dismiss"
   * does: once applied, there is nothing more for it to show.
   */
  protected onUseSuggestion(): void {
    const current = this.suggestion();
    if (!current) {
      return;
    }
    const applied = applySuggestionToSetup(current);
    const defaults = this.effectiveDefaults(applied.preset);

    this.selectedTopicId.set(applied.topicId);
    this.length.set(applied.length);
    this.preset.set(applied.preset);
    this.unknownKanjiSharePercent.set(
      applied.unknownKanjiSharePercent ?? defaults.unknownKanjiSharePercent,
    );
    this.jlptMix.set(applied.jlptMix ?? defaults.jlptMix);
    this.style.set(applied.style ?? defaults.style);
    this.kanjiTouched.set(applied.unknownKanjiSharePercent !== undefined);
    this.jlptTouched.set(applied.jlptMix !== undefined);
    this.styleTouched.set(applied.style !== undefined);
    this.adjustOpen.set(applied.adjustOpen);

    this.appliedSuggestionId.set(current.id);
    this.suggestion.set(null);
    this.persistSetup();
  }

  protected onDismissSuggestion(): void {
    this.suggestion.set(null);
  }

  // --- generating / gate / error -----------------------------------------

  private runGeneration(payload: TextCreatePayload): void {
    this.state.set('generating');
    this.generationSteps.set(INITIAL_STEPS);

    this.api.createText(payload).then(
      (text) => {
        this.textOut.set(text);
        this.state.set('gate');
      },
      (error: unknown) => {
        if (error instanceof ApiError && error.status === 409) {
          // No OpenAI key configured -- same banner the setup screen
          // already shows for that, reused rather than inventing a second
          // way to say it (brief: "a 409 from generation also lands here").
          this.hasOpenAiKey.set(false);
          this.state.set('setup');
          return;
        }
        this.errorMessage.set(
          error instanceof Error ? error.message : 'The text could not be generated.',
        );
        this.state.set('error');
      },
    );
  }

  protected onRetry(): void {
    if (this.lastPayload) {
      this.runGeneration(this.lastPayload);
    }
  }

  protected onBackToSetup(): void {
    this.state.set('setup');
  }

  protected onStart(): void {
    const text = this.textOut();
    if (!text) {
      return;
    }
    this.api.createSession(text.id).then(
      (session) => {
        this.router.navigate(['/read', session.id]);
      },
      () => undefined, // The gate just stays up; pressing Start again retries.
    );
  }

  // --- gate's derived display values --------------------------------------

  protected gateCharacterCount(): number {
    return this.textOut()?.metrics.characters ?? 0;
  }

  protected gateEstimatedMinutes(): number {
    const characters = this.gateCharacterCount();
    return Math.max(1, Math.round(characters / this.paceCharsPerMinute()));
  }

  protected gateUnknownKanjiPercent(): number {
    const share = this.textOut()?.metrics.unknown_kanji_share ?? 0;
    return Math.round(share * 100);
  }

  protected gateJlptMix(): JlptShares {
    const mix = this.textOut()?.metrics.jlpt_mix;
    if (!mix) {
      return { n5: 0, n4: 0, n3: 0, n2: 0, n1: 0 };
    }
    return {
      n5: Math.round(mix.n5 * 100),
      n4: Math.round(mix.n4 * 100),
      n3: Math.round(mix.n3 * 100),
      n2: Math.round(mix.n2 * 100),
      n1: Math.round(mix.n1 * 100),
    };
  }

  // --- setup persistence (try/catch -- localStorage can throw or be absent) --

  private persistSetup(): void {
    try {
      const stored: StoredSetup = {
        topicId: this.selectedTopicId(),
        length: this.length(),
        preset: this.preset(),
        unknownKanjiSharePercent: this.unknownKanjiSharePercent(),
        jlptMix: this.jlptMix(),
        style: this.style(),
        touched: {
          style: this.styleTouched(),
          kanji: this.kanjiTouched(),
          jlpt: this.jlptTouched(),
        },
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    } catch {
      // Private browsing, a full quota, no localStorage at all -- the
      // setup just resets to the defaults next time, which is fine.
    }
  }

  private restoreSetup(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return;
      }
      const stored = JSON.parse(raw) as StoredSetup;
      if (stored.topicId) {
        this.selectedTopicId.set(stored.topicId);
      }
      if (stored.length) {
        this.length.set(stored.length);
      }
      if (stored.preset) {
        this.preset.set(stored.preset);
      }
      if (typeof stored.unknownKanjiSharePercent === 'number') {
        this.unknownKanjiSharePercent.set(stored.unknownKanjiSharePercent);
      }
      if (stored.jlptMix) {
        this.jlptMix.set(stored.jlptMix);
      }
      if (stored.style) {
        this.style.set(stored.style);
      }
      if (stored.touched) {
        this.styleTouched.set(!!stored.touched.style);
        this.kanjiTouched.set(!!stored.touched.kanji);
        this.jlptTouched.set(!!stored.touched.jlpt);
      }
    } catch {
      // Corrupt or inaccessible storage -- start from the defaults.
    }
  }
}
