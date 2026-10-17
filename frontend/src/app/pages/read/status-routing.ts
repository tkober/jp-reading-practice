import type { SessionAnswerApi, SessionStatusApi } from '../../core/api.types';

export type SessionScreen = 'reading' | 'questions' | 'finished';

/**
 * Which screen `/read/:sessionId` shows for a given server `status` --
 * pure and tiny on purpose, pulled out of `ReadSessionPage` so the one
 * decision the brief calls out ("the page's status routing") has its own
 * unit test independent of the component's DOM/timer wiring.
 */
export function screenForStatus(status: SessionStatusApi): SessionScreen {
  switch (status) {
    case 'reading':
      return 'reading';
    case 'questions':
      return 'questions';
    case 'finished':
      return 'finished';
  }
}

/**
 * Which question to resume on when entering the `questions` phase --
 * the first one with no answer yet, or `0` if every question somehow
 * already has one (should not happen while `status` is still
 * `questions`, but resuming at the first question is a safe fallback
 * rather than throwing).
 */
export function firstUnansweredQuestionIndex(answers: readonly SessionAnswerApi[]): number {
  const index = answers.findIndex((answer) => answer.option_index === null);
  return index === -1 ? 0 : index;
}
