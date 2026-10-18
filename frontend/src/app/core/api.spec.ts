import { HttpErrorResponse } from '@angular/common/http';
import { describe, expect, it } from 'vitest';

import { ApiError, rethrow } from './api';

function httpError(status: number, detail?: string): HttpErrorResponse {
  return new HttpErrorResponse({
    status,
    error: detail === undefined ? {} : { detail },
  });
}

function caught(error: unknown): ApiError {
  try {
    rethrow(error);
  } catch (e) {
    return e as ApiError;
  }
  throw new Error('rethrow did not throw');
}

describe('rethrow', () => {
  it('shows a 409 detail as-is, no "The server refused:" lead-in', () => {
    const err = caught(httpError(409, 'No OpenAI API key is configured.'));
    expect(err.message).toBe('No OpenAI API key is configured.');
    expect(err.status).toBe(409);
  });

  it("shows a 502 detail as-is -- app/openai_errors.py's own sentence", () => {
    const detail = 'OpenAI is having problems right now — try again in a moment.';
    const err = caught(httpError(502, detail));
    expect(err.message).toBe(detail);
    expect(err.status).toBe(502);
  });

  it('still adds the lead-in for a 422', () => {
    const err = caught(httpError(422, 'Title is required.'));
    expect(err.message).toBe('The server refused: Title is required.');
  });

  it('still adds the lead-in for a 404', () => {
    const err = caught(httpError(404, 'Text not found.'));
    expect(err.message).toBe('The server refused: Text not found.');
  });

  it('falls back to a bare status line when a 409/502 has no detail', () => {
    const err = caught(httpError(502));
    expect(err.message).toBe('The server answered with 502.');
  });

  it('keeps the unreachable message for status 0 regardless of detail', () => {
    const err = caught(httpError(0, 'irrelevant'));
    expect(err.message).toBe('The server is not reachable.');
    expect(err.status).toBe(0);
  });

  it('rethrows anything that is not an HttpErrorResponse untouched', () => {
    const original = new Error('boom');
    expect(() => rethrow(original)).toThrow(original);
  });
});
