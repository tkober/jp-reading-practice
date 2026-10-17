import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import type {
  KanjiTrainerStatus,
  ModelCatalog,
  Settings,
  SettingsPatch,
  TopicApi,
  TopicCreatePayload,
  TopicUpdatePayload,
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

  // --- plumbing -------------------------------------------------------------

  private get<T>(url: string): Promise<T> {
    return firstValueFrom(this.http.get<T>(url)).catch(rethrow);
  }
}

/**
 * Turn an HTTP failure into a sentence.
 *
 * The backend's `detail` names the cause precisely and is worth showing
 * verbatim, but on its own it reads like a stack trace, so it gets a lead-in.
 */
function rethrow(error: unknown): never {
  if (error instanceof HttpErrorResponse) {
    const detail = typeof error.error?.detail === 'string' ? error.error.detail : '';
    if (error.status === 0) {
      throw new ApiError('The server is not reachable.', error.status);
    }
    throw new ApiError(
      detail ? `The server refused: ${detail}` : `The server answered with ${error.status}.`,
      error.status,
    );
  }
  throw error;
}
