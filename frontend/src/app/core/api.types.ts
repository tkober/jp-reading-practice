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

// --- Text analysis / generation (issues #7, #8) -----------------------------

/** Mirrors the backend's `RubySegment`. */
export interface ApiRubySegment {
  base: string;
  reading: string | null;
}

/** Mirrors the backend's `KanjiInfo`. */
export interface ApiKanjiInfo {
  character: string;
  jlpt: number | null;
  known: boolean;
}

/** Mirrors the backend's `Token` (`backend/app/models.py`) -- the full
 *  per-word analysis, as opposed to the leaner `SumiReadingWord` the
 *  reading screen actually renders (see `features/read/reading/
 *  token-mapping.ts`, which maps this down to that). */
export interface ApiToken {
  id: string;
  surface: string;
  lemma: string;
  reading: string;
  lemma_reading: string;
  pos: string;
  segments: ApiRubySegment[];
  jlpt: number | null;
  kanji: ApiKanjiInfo[];
  known_word: boolean;
  needs_furigana: boolean;
  is_word: boolean;
}

export interface ApiParagraph {
  tokens: ApiToken[];
}

/** Mirrors the backend's `JlptMix` -- *measured* shares (0..1), as opposed
 *  to `JlptMixTargetApi`'s *target* shares. */
export interface ApiJlptMix {
  n5: number;
  n4: number;
  n3: number;
  n2: number;
  n1: number;
  unlisted: number;
}

export interface ApiMetrics {
  characters: number;
  words: number;
  kanji_total: number;
  kanji_unknown: number;
  unknown_kanji_share: number;
  jlpt_mix: ApiJlptMix;
}

/** Mirrors the backend's `JlptMixTarget` -- every share optional (0 default). */
export interface JlptMixTargetApi {
  n5?: number;
  n4?: number;
  n3?: number;
  n2?: number;
  n1?: number;
}

export type ReadingLengthApi = 'short' | 'medium' | 'long';
export type DifficultyPresetApi = 'easy' | 'stretch' | 'challenge';

/** Mirrors the backend's `TextOverrides` -- every field optional. */
export interface TextOverridesApi {
  style?: TopicStyleApi;
  unknown_kanji_target?: number;
  jlpt_mix?: JlptMixTargetApi;
}

/** Mirrors the backend's `TextCreateRequest`, `POST /api/texts`'s body. */
export interface TextCreatePayload {
  topic_slug: string;
  length: ReadingLengthApi;
  preset: DifficultyPresetApi;
  overrides?: TextOverridesApi;
}

/** Mirrors the backend's `QuestionOut` -- never carries `answer_index`. */
export interface ApiQuestion {
  question: string;
  options: string[];
}

/** Mirrors the backend's `TextTargets`. */
export interface ApiTextTargets {
  topic_slug: string;
  length: ReadingLengthApi;
  preset: DifficultyPresetApi;
  unknown_kanji_target: number;
  jlpt_mix: Required<JlptMixTargetApi>;
  style: TopicStyleApi;
}

/** Mirrors the backend's `TextOut` -- `POST /api/texts`/`GET /api/texts/{id}`. */
export interface TextOutApi {
  id: number;
  title: string;
  paragraphs: ApiParagraph[];
  questions: ApiQuestion[];
  metrics: ApiMetrics;
  targets: ApiTextTargets;
  attempts: number;
  model: string;
  cost_usd: number | null;
  kanji_trainer_error: string | null;
}

// --- Reading sessions (issue #9) --------------------------------------------

export type SessionStatusApi = 'reading' | 'questions' | 'finished';

/** Mirrors the backend's `SessionAnswerOut`. */
export interface SessionAnswerApi {
  option_index: number | null;
  correct_index: number | null;
}

/** Mirrors the backend's `SessionOut`. */
export interface SessionOutApi {
  id: number;
  text: TextOutApi;
  status: SessionStatusApi;
  started_at: string;
  active_ms: number;
  paused_ms: number;
  answers: SessionAnswerApi[];
  comprehension_correct: number | null;
}

export interface SessionTimePayload {
  active_ms: number;
  paused_ms: number;
}

export interface SessionTimeApi {
  active_ms: number;
  paused_ms: number;
}

/** Only `reading_peek` is ever sent from the browser today -- see the
 *  backend's own `HelpKind` doc comment. */
export type HelpKindApi = 'reading_peek';

export interface HelpPayload {
  kind: HelpKindApi;
  token_id: string;
}

export interface HelpResultApi {
  counted: boolean;
  weight: number;
}

/** Mirrors the backend's `WordLookupOut`, `POST /api/sessions/{id}/lookups`. */
export interface WordLookupApi {
  surface: string;
  lemma: string;
  reading: string;
  jlpt: number | null;
  meanings: string[];
  known_status: string;
}

/**
 * The word popover's three LLM helps (issue #10), `POST /api/sessions/{id}/
 * assist`'s own kind -- narrower than `WordActionKind` (`features/read/
 * reading/reading.types.ts`), which still carries `'tutor'` for the design
 * (#11's own, separate endpoint once it exists).
 */
export type AssistKindApi = 'explain' | 'translate' | 'grammar';

export interface AssistPayload {
  kind: AssistKindApi;
  token_id: string;
}

/** Mirrors the backend's `AssistResult`. */
export interface AssistResultApi {
  kind: AssistKindApi;
  answer: string;
  cached: boolean;
  counted: boolean;
  weight: number;
}

// --- Tutor chat (issue #11) --------------------------------------------------

export type ChatRoleApi = 'user' | 'assistant';

/** Mirrors the backend's `ChatMessageOut`. */
export interface ChatMessageApi {
  id: number;
  role: ChatRoleApi;
  content: string;
  focus_sentence_key: string | null;
  model: string | null;
  cost_usd: number | null;
  created_at: string;
}

/** Mirrors the backend's `ChatRequest`, `POST /api/sessions/{id}/chat`'s
 *  body -- `focus_token_id` unset for a question with no focus (opened
 *  from the session bar rather than "Ask tutor"). */
export interface ChatPayload {
  content: string;
  focus_token_id?: string;
}

/** Mirrors the backend's `ChatResult`. */
export interface ChatResultApi {
  user_message: ChatMessageApi;
  assistant_message: ChatMessageApi;
  counted: boolean;
  weight: number;
}

export interface AnswerPayload {
  question_index: number;
  option_index: number;
}

export interface AnswerResultApi {
  correct: boolean;
  correct_index: number;
}

export interface FinishReadingPayload {
  active_ms: number;
  paused_ms: number;
}

export interface LookedUpWordApi {
  word: string;
  reading: string;
  meaning: string;
}

/** Mirrors the backend's `SessionSummaryOut`. */
export interface SessionSummaryApi {
  chars_per_minute: number;
  words_per_minute: number;
  helps_per_100_words: number;
  questions_correct: number;
  questions_total: number;
  active_ms: number;
  looked_up_words: LookedUpWordApi[];
  /** Sum of this session's own assist (issue #10) *and* tutor-chat (issue
   *  #11) generation costs -- 0 for an assist cache hit (the chat never
   *  caches). Not shown anywhere yet -- History/Stats (issue #12) read
   *  `GET /api/history`/`GET /api/stats` instead of this per-session
   *  summary; kept here so this type matches the backend. */
  assists_cost_usd: number;
  /** Number of tutor-chat questions asked this session (issue #11). */
  chat_questions: number;
}

/** Mirrors the backend's `ReadingPaceOut`, `GET /api/reading/pace`. */
export interface ReadingPaceApi {
  chars_per_minute: number;
  source: 'default' | 'history';
  sessions: number;
}

// --- History / Stats / Export (issue #12) ------------------------------------

/** Mirrors the backend's `HistoryEntryOut`, one row of `GET /api/history`,
 *  oldest first (see that model's own docstring). `finished === false`
 *  (a `reading`/`questions` session) means the four fields below are all
 *  `null` -- `pages/history/history-mapping.ts`'s `toHistorySession` turns
 *  this into the "In progress" row. */
export interface HistoryEntryApi {
  id: number;
  date: string;
  title: string;
  topic_name: string;
  length: 'short' | 'medium' | 'long';
  finished: boolean;
  speed_chars_per_minute: number | null;
  helps_per_100_words: number | null;
  comprehension_correct: number | null;
  comprehension_total: number | null;
}

/** Mirrors the backend's `StatsSummaryOut` -- see `app.stats_math` for what
 *  each number means and which constants define it. */
export interface StatsSummaryApi {
  speed_chars_per_minute: number;
  speed_delta_percent: number | null;
  helps_per_100_words: number;
  comprehension_percent: number;
  reading_level: string;
  reading_level_detail: string;
}

/** Mirrors the backend's `SeriesPointOut`. */
export interface SeriesPointApi {
  date: string;
  value: number;
}

/** Mirrors the backend's `SpeedByGroupOut`. */
export interface SpeedByGroupApi {
  label: string;
  value: number;
}

/** Mirrors the backend's `ProblemWordOut`. */
export interface ProblemWordApi {
  word: string;
  reading: string;
  meaning: string;
  times_looked_up: number;
}

/** Mirrors the backend's `StatsOut`, `GET /api/stats` -- `summary` (and
 *  every list) is `null`/empty together under three finished sessions. */
export interface StatsApi {
  summary: StatsSummaryApi | null;
  speed_series: SeriesPointApi[];
  helps_series: SeriesPointApi[];
  speed_by_style: SpeedByGroupApi[];
  speed_by_topic: SpeedByGroupApi[];
  problem_words: ProblemWordApi[];
}

/**
 * `GET /api/export`'s response -- every row the learner has ever generated
 * or done. Deliberately loose (`Record<string, unknown>` per row rather
 * than mirroring every backend export model field by field): the frontend
 * only ever serialises this straight back out to a downloaded `.json` file
 * (`pages/history/history.ts`'s `exportData`), it never reads a field of
 * its own, so a full mirror here would just be upkeep with no payoff.
 */
export interface ExportApi {
  exported_at: string;
  topics: Record<string, unknown>[];
  texts: Record<string, unknown>[];
  sessions: Record<string, unknown>[];
  help_events: Record<string, unknown>[];
  chat_messages: Record<string, unknown>[];
}
