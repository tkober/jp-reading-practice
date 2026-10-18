import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import type {
  AnswerPayload,
  AnswerResultApi,
  AssistPayload,
  AssistResultApi,
  ChatMessageApi,
  ChatPayload,
  ChatResultApi,
  ExportApi,
  FinishReadingPayload,
  HelpPayload,
  HelpResultApi,
  HistoryEntryApi,
  KanjiTrainerStatus,
  ModelCatalog,
  PresetsApi,
  ReadingPaceApi,
  SessionOutApi,
  SessionSummaryApi,
  SessionTimeApi,
  SessionTimePayload,
  Settings,
  SettingsPatch,
  StatsApi,
  SuggestionApi,
  TextCreatePayload,
  TextOutApi,
  TopicApi,
  TopicCreatePayload,
  TopicUpdatePayload,
  WordLookupApi,
} from './api.types';

/**
 * What every call below rethrows as, carrying the original HTTP status
 * alongside the friendly message -- `rethrow()` always produces one of
 * these (or `KanjiTrainerStatusUnavailable`), never a bare `HttpErrorResponse`,
 * so callers get a sentence without losing the status `core/unreachable.ts`'s
 * `isBackendUnreachable()` needs for the T6 decision.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/**
 * Raised by `kanjiTrainerStatus()` when the backend does not have the
 * endpoint yet (a 404, not an outage -- see issue #5). Kept distinct from
 * the generic `rethrow()` message so the Settings screen can show its own
 * sentence instead of "The server answered with 404.".
 */
export class KanjiTrainerStatusUnavailable extends Error {
  constructor() {
    super('Connection test not available in this backend version.');
  }
}

/**
 * The one place that talks HTTP.
 *
 * Same-origin throughout: in a future deployment nginx would serve the SPA
 * and proxy `/api` to the backend over the internal network, so the browser
 * always talks to whatever address it loaded the page from and no base URL
 * is ever configured here -- same assumption as the other apps in the suite.
 */
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  // --- settings -----------------------------------------------------------

  settings(): Promise<Settings> {
    return this.get('/api/settings');
  }

  saveSettings(patch: SettingsPatch): Promise<Settings> {
    return firstValueFrom(this.http.put<Settings>('/api/settings', patch)).catch(rethrow);
  }

  modelCatalog(): Promise<ModelCatalog> {
    return this.get('/api/settings/models');
  }

  /**
   * The parallel backend work (issue #5) adds this endpoint; until it does,
   * the backend answers 404 for an unknown route, which is not the same as
   * the backend being unreachable -- see `KanjiTrainerStatusUnavailable`.
   */
  kanjiTrainerStatus(): Promise<KanjiTrainerStatus> {
    return firstValueFrom(this.http.get<KanjiTrainerStatus>('/api/kanji-trainer/status')).catch(
      (error: unknown) => {
        if (error instanceof HttpErrorResponse && error.status === 404) {
          throw new KanjiTrainerStatusUnavailable();
        }
        return rethrow(error);
      },
    );
  }

  // --- topics (issue #8) ---------------------------------------------------

  topics(): Promise<TopicApi[]> {
    return this.get('/api/topics');
  }

  topic(id: number): Promise<TopicApi> {
    return this.get(`/api/topics/${id}`);
  }

  createTopic(payload: TopicCreatePayload): Promise<TopicApi> {
    return firstValueFrom(this.http.post<TopicApi>('/api/topics', payload)).catch(rethrow);
  }

  updateTopic(id: number, payload: TopicUpdatePayload): Promise<TopicApi> {
    return firstValueFrom(this.http.put<TopicApi>(`/api/topics/${id}`, payload)).catch(rethrow);
  }

  resetTopic(id: number): Promise<TopicApi> {
    return firstValueFrom(this.http.post<TopicApi>(`/api/topics/${id}/reset`, {})).catch(rethrow);
  }

  deleteTopic(id: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/topics/${id}`)).catch(rethrow);
  }

  // --- text generation (issue #8) ------------------------------------------

  createText(payload: TextCreatePayload): Promise<TextOutApi> {
    return firstValueFrom(this.http.post<TextOutApi>('/api/texts', payload)).catch(rethrow);
  }

  text(id: number): Promise<TextOutApi> {
    return this.get(`/api/texts/${id}`);
  }

  readingPace(): Promise<ReadingPaceApi> {
    return this.get('/api/reading/pace');
  }

  /**
   * The three presets' resolved generation targets (issue #13) -- `stretch`
   * resolved at its current, adaptive difficulty. The setup screen reads
   * this instead of its own hard-coded `DIFFICULTY_PRESETS` table.
   */
  presets(): Promise<PresetsApi> {
    return this.get('/api/presets');
  }

  // --- reading sessions (issue #9) ------------------------------------------

  createSession(textId: number): Promise<SessionOutApi> {
    return firstValueFrom(
      this.http.post<SessionOutApi>('/api/sessions', { text_id: textId }),
    ).catch(rethrow);
  }

  session(id: number): Promise<SessionOutApi> {
    return this.get(`/api/sessions/${id}`);
  }

  heartbeat(id: number, payload: SessionTimePayload): Promise<SessionTimeApi> {
    return firstValueFrom(this.http.put<SessionTimeApi>(`/api/sessions/${id}/time`, payload)).catch(
      rethrow,
    );
  }

  /**
   * Same heartbeat, sent with `keepalive` so it survives the page becoming
   * hidden (a backgrounded tab on a phone) -- `HttpClient` has no
   * `keepalive` option, so this one call bypasses it for a plain `fetch`
   * (brief: "on `visibilitychange` hidden (`keepalive` fetch)"). Fire-and-
   * forget: nothing reads the response, and nothing here can retry it
   * anyway once the page is gone.
   */
  heartbeatKeepalive(id: number, payload: SessionTimePayload): void {
    fetch(`/api/sessions/${id}/time`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => undefined);
  }

  logHelp(id: number, payload: HelpPayload): Promise<HelpResultApi> {
    return firstValueFrom(
      this.http.post<HelpResultApi>(`/api/sessions/${id}/helps`, payload),
    ).catch(rethrow);
  }

  lookupWord(id: number, tokenId: string): Promise<WordLookupApi> {
    return firstValueFrom(
      this.http.post<WordLookupApi>(`/api/sessions/${id}/lookups`, { token_id: tokenId }),
    ).catch(rethrow);
  }

  /**
   * Explain word / Translate sentence / Explain grammar (issue #10). A
   * cache hit (`cached: true`) and a freshly generated answer come back
   * through the same promise -- the caller does not need to tell them
   * apart to render the result, only to decide whether a repeat ask is
   * worth the wait (it never is: see `cached`).
   */
  assist(id: number, payload: AssistPayload): Promise<AssistResultApi> {
    return firstValueFrom(
      this.http.post<AssistResultApi>(`/api/sessions/${id}/assist`, payload),
    ).catch(rethrow);
  }

  /**
   * The tutor chat (issue #11). `chatHistory` is what a reload replays into
   * the panel; `sendChat` stores the user's message and asks for an
   * answer in the same request -- the caller never sees the two halves
   * separately (there is no "pending" shape the backend itself reports,
   * `chatSending` on the page is purely a local "waiting for this
   * promise" flag).
   */
  chatHistory(id: number): Promise<ChatMessageApi[]> {
    return this.get(`/api/sessions/${id}/chat`);
  }

  sendChat(id: number, payload: ChatPayload): Promise<ChatResultApi> {
    return firstValueFrom(this.http.post<ChatResultApi>(`/api/sessions/${id}/chat`, payload)).catch(
      rethrow,
    );
  }

  finishReading(id: number, payload: FinishReadingPayload): Promise<SessionOutApi> {
    return firstValueFrom(
      this.http.post<SessionOutApi>(`/api/sessions/${id}/finish-reading`, payload),
    ).catch(rethrow);
  }

  answerQuestion(id: number, payload: AnswerPayload): Promise<AnswerResultApi> {
    return firstValueFrom(
      this.http.post<AnswerResultApi>(`/api/sessions/${id}/answers`, payload),
    ).catch(rethrow);
  }

  summary(id: number): Promise<SessionSummaryApi> {
    return this.get(`/api/sessions/${id}/summary`);
  }

  // --- AI suggestions (issue #14) -------------------------------------------

  /**
   * "Suggest next text" on the setup screen -- one suggestion, based on the
   * learner's own history/stats/Stretch settings; the backend stores it so
   * `createText()`'s own `suggestion_id` can mark it used later.
   */
  suggestNext(): Promise<SuggestionApi> {
    return firstValueFrom(
      this.http.post<SuggestionApi>('/api/suggestions', { local_hour: new Date().getHours() }),
    ).catch(rethrow);
  }

  // --- History / Stats / Export (issue #12) ---------------------------------

  history(): Promise<HistoryEntryApi[]> {
    return this.get('/api/history');
  }

  stats(): Promise<StatsApi> {
    return this.get('/api/stats');
  }

  export(): Promise<ExportApi> {
    return this.get('/api/export');
  }

  // --- plumbing -------------------------------------------------------------

  private get<T>(url: string): Promise<T> {
    return firstValueFrom(this.http.get<T>(url)).catch(rethrow);
  }
}

/**
 * Turn an HTTP failure into a sentence.
 *
 * The backend's `detail` names the cause precisely and is worth showing
 * verbatim, but on its own it reads like a stack trace, so it gets a lead-in
 * -- except for 409/502, where `detail` is already a complete, learner-
 * facing sentence (the "no OpenAI key"/"wrong session phase" 409s, and
 * every OpenAI-upstream 502 `app/openai_errors.py` formats): the word
 * popover, the tutor chat, the "Suggest next text" card and the generation
 * error screen show it as-is there, with no added lead-in to double up on.
 *
 * Exported for `api.spec.ts` -- otherwise only called from within this file.
 */
export function rethrow(error: unknown): never {
  if (error instanceof HttpErrorResponse) {
    const detail = typeof error.error?.detail === 'string' ? error.error.detail : '';
    if (error.status === 0) {
      throw new ApiError('The server is not reachable.', error.status);
    }
    if (detail && (error.status === 409 || error.status === 502)) {
      throw new ApiError(detail, error.status);
    }
    throw new ApiError(
      detail ? `The server refused: ${detail}` : `The server answered with ${error.status}.`,
      error.status,
    );
  }
  throw error;
}
