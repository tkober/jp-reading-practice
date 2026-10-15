import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  SumiButtonDirective,
  SumiInputDirective,
  SumiSelectDirective,
  SumiToggle,
} from 'sumi-ui/forms';
import { SumiBanner, SumiCard, SumiErrorState, SumiPage } from 'sumi-ui/layout';

import { Api, KanjiTrainerStatusUnavailable } from '../../core/api';
import type {
  KanjiTrainerStatus,
  ModelOption,
  ModelSlot,
  Settings,
  SettingsPatch,
} from '../../core/api.types';
import { isBackendUnreachable } from '../../core/unreachable';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/**
 * Sentinel option value that switches a model slot from the dropdown to a
 * text box. Not a valid model id, so it can never collide with a real one --
 * same pattern as jp-conversation-practice's settings page.
 */
const CUSTOM = '__custom__';

@Component({
  selector: 'app-settings',
  imports: [
    FormsModule,
    SumiBanner,
    SumiButtonDirective,
    SumiCard,
    SumiErrorState,
    SumiInputDirective,
    SumiPage,
    SumiSelectDirective,
    SumiToggle,
  ],
  templateUrl: './settings.html',
  styleUrl: './settings.scss',
})
export class SettingsPage {
  private readonly api = inject(Api);

  protected readonly customValue = CUSTOM;

  protected readonly current = signal<Settings | null>(null);
  protected readonly modelSlots = signal<ModelSlot[]>([]);
  /** Why the dropdowns only show curated entries, when that is the case. */
  protected readonly modelListNote = signal<string | null>(null);
  protected readonly loadError = signal<string | null>(null);
  /** The settings themselves could not be loaded at all -- T6, not a banner. */
  protected readonly failed = signal(false);
  protected readonly saveState = signal<SaveState>('idle');
  protected readonly saveMessage = signal<string | null>(null);

  /** Only the fields the user actually touched are sent. */
  private readonly draft = signal<SettingsPatch>({});

  /** The key is write-only: an empty box means "leave as is". */
  protected readonly openaiKeyInput = signal('');

  /**
   * Slots the user switched to free text. Sticky, because picking "Other
   * model…" leaves the old -- still valid -- value in place, so the text
   * box cannot be derived from the value alone.
   */
  private readonly customSlots = signal<ReadonlySet<string>>(new Set());

  protected readonly dirty = computed(
    () => Object.keys(this.draft()).length > 0 || this.openaiKeyInput().length > 0,
  );

  // --- Kanji Trainer connection test ------------------------------------

  protected readonly kanjiTrainerTesting = signal(false);
  protected readonly kanjiTrainerStatus = signal<KanjiTrainerStatus | null>(null);
  protected readonly kanjiTrainerMessage = signal<string | null>(null);
  /** Whether `kanjiTrainerMessage` is "not available yet" rather than a real failure. */
  protected readonly kanjiTrainerUnavailable = signal(false);

  constructor() {
    this.reload();
    this.api.modelCatalog().then(
      (catalog) => {
        this.modelSlots.set(catalog.slots);
        this.modelListNote.set(catalog.live_ok ? null : catalog.live_detail);
      },
      () => this.modelListNote.set('The model list could not be loaded.'),
    );
  }

  reload(): void {
    this.api.settings().then(
      (settings) => {
        this.failed.set(false);
        this.current.set(settings);
        this.draft.set({});
        this.customSlots.set(new Set());
        this.loadError.set(null);
      },
      (error: unknown) => {
        if (isBackendUnreachable(error)) {
          this.failed.set(true);
        } else {
          this.loadError.set((error as Error).message);
        }
      },
    );
  }

  value(key: keyof SettingsPatch): string {
    const draft = this.draft()[key];
    if (draft !== undefined) {
      return String(draft);
    }
    const settings = this.current();
    return settings ? String(settings[key as keyof Settings] ?? '') : '';
  }

  set(key: keyof SettingsPatch, value: string): void {
    this.draft.update((current) => ({ ...current, [key]: value }));
    this.saveState.set('idle');
  }

  protected readonly webSearchEnabled = computed<boolean>(() => {
    const draft = this.draft().web_search_enabled;
    return draft !== undefined ? draft : (this.current()?.web_search_enabled ?? false);
  });

  setWebSearch(value: boolean): void {
    this.draft.update((current) => ({ ...current, web_search_enabled: value }));
    this.saveState.set('idle');
  }

  // --- model slots -------------------------------------------------------

  /**
   * The catalog's slot key (`generation`/`help`) is not the settings field
   * name (`generation_model`/`help_model`) -- this is the one place that
   * maps between them.
   */
  protected slotField(slot: ModelSlot): 'generation_model' | 'help_model' {
    return slot.key === 'generation' ? 'generation_model' : 'help_model';
  }

  /** The option currently configured for a slot, if it is one of the listed ones. */
  selectedOption(slot: ModelSlot): ModelOption | null {
    const id = this.value(this.slotField(slot));
    return slot.options.find((option) => option.id === id) ?? null;
  }

  /**
   * Whether this slot shows the text box instead of the dropdown.
   *
   * Either the user asked for it, or the configured model is not in the
   * list -- a value set before a model was retired, or typed on an earlier
   * visit. A `<select>` renders such a value as blank, so falling back to
   * text keeps it visible rather than silently swallowing it.
   */
  isCustom(slot: ModelSlot): boolean {
    if (this.customSlots().has(slot.key)) {
      return true;
    }
    const id = this.value(this.slotField(slot));
    return id !== '' && !slot.options.some((option) => option.id === id);
  }

  selectValue(slot: ModelSlot): string {
    return this.isCustom(slot) ? CUSTOM : this.value(this.slotField(slot));
  }

  onSlotSelect(slot: ModelSlot, value: string): void {
    this.customSlots.update((current) => {
      const next = new Set(current);
      if (value === CUSTOM) {
        next.add(slot.key);
      } else {
        next.delete(slot.key);
      }
      return next;
    });
    if (value !== CUSTOM) {
      this.set(this.slotField(slot), value);
    }
  }

  /** One line per option: the id, plus what we know that the id does not say. */
  optionText(option: ModelOption): string {
    if (!option.shutdown_date) {
      return option.label;
    }
    // The field is the shutdown date, not the date it was deprecated: it is
    // callable until then, it just has a successor already.
    return `${option.label} — deprecated (shutting down ${option.shutdown_date})`;
  }

  curatedOptions(slot: ModelSlot): ModelOption[] {
    return slot.options.filter((option) => option.curated);
  }

  liveOptions(slot: ModelSlot): ModelOption[] {
    return slot.options.filter((option) => !option.curated);
  }

  // --- saving --------------------------------------------------------------

  save(): void {
    if (!this.dirty() || this.saveState() === 'saving') {
      return;
    }

    const patch: SettingsPatch = { ...this.draft() };
    // Sent only when non-empty, so saving other fields never clears the key.
    if (this.openaiKeyInput().trim()) {
      patch.openai_api_key = this.openaiKeyInput().trim();
    }

    this.saveState.set('saving');
    this.api.saveSettings(patch).then(
      (settings) => {
        this.current.set(settings);
        this.draft.set({});
        // A typed value that turned out to be a listed model settles back
        // into the dropdown; one that did not stays in the text box.
        this.customSlots.set(new Set());
        this.openaiKeyInput.set('');
        this.saveState.set('saved');
        this.saveMessage.set('Saved.');
      },
      (error: unknown) => {
        this.saveState.set('error');
        this.saveMessage.set((error as Error).message);
      },
    );
  }

  /** Clear the stored key so the value from the environment applies again. */
  clearKey(): void {
    this.saveState.set('saving');
    this.api.saveSettings({ openai_api_key: '' }).then(
      (settings) => {
        this.current.set(settings);
        this.saveState.set('saved');
        this.saveMessage.set('Reset — the value from .env applies again.');
      },
      (error: unknown) => {
        this.saveState.set('error');
        this.saveMessage.set((error as Error).message);
      },
    );
  }

  // --- Kanji Trainer connection test ---------------------------------------

  async testKanjiTrainer(): Promise<void> {
    this.kanjiTrainerTesting.set(true);
    this.kanjiTrainerStatus.set(null);
    this.kanjiTrainerMessage.set(null);
    this.kanjiTrainerUnavailable.set(false);
    try {
      this.kanjiTrainerStatus.set(await this.api.kanjiTrainerStatus());
    } catch (error) {
      if (error instanceof KanjiTrainerStatusUnavailable) {
        this.kanjiTrainerUnavailable.set(true);
      }
      this.kanjiTrainerMessage.set((error as Error).message);
    } finally {
      this.kanjiTrainerTesting.set(false);
    }
  }

  /** "Connected · level 12 · 340 kanji · 1200 words known" -- only the parts the backend knows. */
  kanjiTrainerSummary(status: KanjiTrainerStatus): string {
    const parts = ['Connected'];
    if (status.level !== null) {
      parts.push(`level ${status.level}`);
    }
    if (status.known_kanji !== null) {
      parts.push(`${status.known_kanji} kanji`);
    }
    if (status.known_vocabulary !== null) {
      parts.push(`${status.known_vocabulary} words known`);
    }
    return parts.join(' · ');
  }
}
