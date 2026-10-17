/** Mirrors the backend's `SettingsOut` (`backend/app/models.py`). */
export interface Settings {
  generation_model: string;
  help_model: string;
  kanji_trainer_mcp_url: string;
  web_search_enabled: boolean;

  /** The key itself never reaches the browser -- only these three. */
  openai_api_key_set: boolean;
  openai_api_key_hint: string | null;
  openai_api_key_from_env: boolean;
}

/**
 * Mirrors the backend's `SettingsIn`. Every field is optional: omitting one
 * leaves it unchanged, an empty string clears the override so the
 * environment default applies again (`openai_api_key`, `kanji_trainer_mcp_url`).
 */
export interface SettingsPatch {
  openai_api_key?: string;
  generation_model?: string;
  help_model?: string;
  kanji_trainer_mcp_url?: string;
  web_search_enabled?: boolean;
}

/** One entry in a model dropdown -- mirrors `model_catalog.ModelOption.as_dict()`. */
export interface ModelOption {
  id: string;
  label: string;
  description: string | null;
  curated: boolean;
  shutdown_date: string | null;
}

/** One configurable model slot -- mirrors `model_catalog.ModelCatalog.build()`'s per-slot entry. */
export interface ModelSlot {
  key: 'generation' | 'help';
  label: string;
  hint: string;
  options: ModelOption[];
}

/** Mirrors `model_catalog.CatalogResult.as_dict()`, the body of `GET /api/settings/models`. */
export interface ModelCatalog {
  slots: ModelSlot[];
  live_ok: boolean;
  live_detail: string | null;
}

/**
 * The response `GET /api/kanji-trainer/status` is expected to carry, per
 * issue #5 (the parallel backend work this frontend was built against
 * before that endpoint existed). See `core/api.ts`'s `kanjiTrainerStatus()`.
 */
export interface KanjiTrainerStatus {
  reachable: boolean;
  url: string;
  level: number | null;
  known_kanji: number | null;
  known_vocabulary: number | null;
  error: string | null;
}

// --- Topics (issue #8) --------------------------------------------------

export type TopicStyleApi = 'casual' | 'polite' | 'formal';

/** Mirrors the backend's `TopicOut` (`backend/app/models.py`). */
export interface TopicApi {
  id: number;
  slug: string;
  title: string;
  glyph: string;
  prompt: string;
  default_style: TopicStyleApi;
  feed_urls: string[];
  sort_order: number;
  is_builtin: boolean;
  is_customized: boolean;
}

/** Mirrors the backend's `TopicCreate`. */
export interface TopicCreatePayload {
  title: string;
  glyph: string;
  prompt: string;
  default_style: TopicStyleApi;
  feed_urls: string[];
}

/** Mirrors the backend's `TopicUpdate` -- every field optional. */
export interface TopicUpdatePayload {
  title?: string;
  glyph?: string;
  prompt?: string;
  default_style?: TopicStyleApi;
  feed_urls?: string[];
}
