import { describe, expect, it } from 'vitest';
import type { SessionAnswerApi } from '../../core/api.types';
import { firstUnansweredQuestionIndex, screenForStatus } from './status-routing';

describe('screenForStatus', () => {
  it('maps every server status to its own screen', () => {
    expect(screenForStatus('reading')).toBe('reading');
    expect(screenForStatus('questions')).toBe('questions');
    expect(screenForStatus('finished')).toBe('finished');
  });
});

function answer(
  option_index: number | null,
  correct_index: number | null = null,
): SessionAnswerApi {
  return { option_index, correct_index };
}

describe('firstUnansweredQuestionIndex', () => {
  it('resumes at the first unanswered question', () => {
    expect(firstUnansweredQuestionIndex([answer(0, 0), answer(null)])).toBe(1);
  });

  it('starts at 0 when nothing is answered yet', () => {
    expect(firstUnansweredQuestionIndex([answer(null), answer(null)])).toBe(0);
  });

  it('falls back to 0 when every question is already answered', () => {
    expect(firstUnansweredQuestionIndex([answer(0, 0), answer(1, 1)])).toBe(0);
  });

  it('falls back to 0 for an empty list', () => {
    expect(firstUnansweredQuestionIndex([])).toBe(0);
  });
});
