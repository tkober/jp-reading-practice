import { ApiError } from './api';

/**
 * Whether a failed request means the backend itself could not be reached --
 * a connection failure (`status 0`) or the dev proxy answering on its own
 * behalf (5xx) -- rather than the backend producing an application-level
 * error. A page's initial load uses this to decide between T6
 * (`sumi-error-state`, "Try again") and an ordinary banner.
 *
 * Modelled on jp-conversation-practice's `core/unreachable.ts`, with one
 * adaptation: that app's `Api` returns raw `HttpErrorResponse`s, while this
 * one's `core/api.ts` always rethrows into `ApiError` (a friendly message
 * plus the original status) so every caller gets a sentence, not a stack
 * trace -- so this checks `ApiError.status` instead. A genuine 404 (the
 * Kanji Trainer status endpoint before issue #5 lands) is handled
 * separately in `core/api.ts`'s `kanjiTrainerStatus()`, never folded in here.
 */
export function isBackendUnreachable(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  return error.status === 0 || error.status >= 500;
}
