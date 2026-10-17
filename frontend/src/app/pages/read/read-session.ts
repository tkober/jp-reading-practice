import { DOCUMENT } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { SumiButtonDirective } from 'sumi-ui/forms';
import { SumiErrorState } from 'sumi-ui/layout';

import { Api, ApiError } from '../../core/api';
import type {
  ApiParagraph,
  ApiToken,
  SessionOutApi,
  SessionSummaryApi,
} from '../../core/api.types';
import type { ComprehensionQuestion } from '../../features/read/questions/questions.types';
import { QuestionsScreen } from '../../features/read/questions/questions-screen';
import type {
  ChatMessage,
  ReadingTextData,
  ReadingWord,
  WordActionKind,
  WordActionOption,
  WordActivateEvent,
  WordAnswer,
  WordDetails,
} from '../../features/read/reading/reading.types';
import { ReadingScreen } from '../../features/read/reading/reading-screen';
import { SummaryScreen } from '../../features/read/summary/summary-screen';
import type { LookedUpWord } from '../../features/read/summary/summary.types';
import { ActiveTimeTracker } from './active-time-tracker';
import { sentenceForToken, truncateForChip } from './sentence-for-token';
import { firstUnansweredQuestionIndex, screenForStatus } from './status-routing';
import { mapApiParagraphsToReadingText } from './token-mapping';

type SessionPageState = 'loading' | 'reading' | 'questions' | 'finished' | 'error';

const TICK_INTERVAL_MS = 1000;
const HEARTBEAT_INTERVAL_MS = 15_000;
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'scroll', 'touchstart', 'wheel'] as const;

/**
 * The word popover's four real action buttons -- labels and weights
 * exactly as the approved design/fixture (`preview/fixtures/
 * word-lookup.fixture.ts`'s `WORD_ACTIONS`) show them. "Ask tutor" (issue
 * #11) opens the chat panel with this word's sentence as its focus
 * (`onWordAction` below) rather than calling `Api.assist()` like the other
 * three.
 */
const WORD_ACTIONS: readonly WordActionOption[] = [
  { kind: 'explain', label: 'Explain word', weight: 2 },
  { kind: 'translate', label: 'Translate sentence', weight: 3 },
  { kind: 'grammar', label: 'Explain grammar', weight: 3 },
  { kind: 'tutor', label: 'Ask tutor', weight: 3 },
];

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/**
 * `/read/:sessionId`: the running session -- reading, questions and
 * summary, picked from the server's own `status` on every load (issue
 * #9), so a reload or switching apps on the phone resumes exactly where
 * the reader was, active time included. Everything before a session
 * exists (setup/generating/gate/error) is `ReadPage` (`/read`) instead.
 */
@Component({
  selector: 'app-read-session',
  templateUrl: './read-session.html',
  imports: [ReadingScreen, QuestionsScreen, SummaryScreen, SumiErrorState, SumiButtonDirective],
})
export class ReadSessionPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly state = signal<SessionPageState>('loading');
  protected readonly errorMessage = signal('');

  private readonly session = signal<SessionOutApi | null>(null);
  private tokensById = new Map<string, ApiToken>();
  private paragraphs: readonly ApiParagraph[] = [];

  // --- reading phase ------------------------------------------------------

  protected readonly readingText = signal<ReadingTextData>({ titleJapanese: '', paragraphs: [] });
  protected readonly elapsedLabel = signal('0:00');
  protected readonly paused = signal(false);
  protected readonly selectedWordId = signal<string | null>(null);
  protected readonly selectedWord = signal<WordDetails | null>(null);
  protected readonly wordAnswer = signal<WordAnswer | null>(null);
  protected readonly wordActionLoading = signal<WordActionKind | null>(null);

  // --- tutor chat (issue #11) ----------------------------------------------

  protected readonly chatOpen = signal(false);
  protected readonly chatMessages = signal<readonly ChatMessage[]>([]);
  protected readonly chatSending = signal(false);
  /** The next question's focus, already resolved to its chip display text
   *  -- `null` for no focus. */
  protected readonly chatFocusLabel = signal<string | null>(null);
  private chatFocusTokenId: string | null = null;

  private tracker: ActiveTimeTracker | null = null;
  private tickHandle: ReturnType<typeof setInterval> | null = null;
  private heartbeatHandle: ReturnType<typeof setInterval> | null = null;
  private activityListener = (): void => this.tracker?.noteActivity();
  private visibilityListener = (): void => this.onVisibilityChange();
  private readonly peekedLemmas = new Set<string>();
  private readingTimersStarted = false;

  // --- questions phase ------------------------------------------------------

  protected readonly currentQuestionIndex = signal(0);
  protected readonly selectedOptionId = signal<string | null>(null);
  protected readonly answered = signal(false);
  protected readonly currentQuestion = signal<ComprehensionQuestion>({
    id: 'q0',
    textEnglish: '',
    options: [],
    correctOptionId: '',
  });
  protected readonly totalQuestions = signal(0);

  // --- summary phase ------------------------------------------------------

  protected readonly summary = signal<SessionSummaryApi | null>(null);

  constructor() {
    const route = inject(ActivatedRoute);
    route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = Number(params.get('sessionId'));
      this.stopReadingTimers();
      if (Number.isFinite(id)) {
        this.loadSession(id);
      } else {
        this.state.set('error');
        this.errorMessage.set('Invalid session.');
      }
    });

    this.destroyRef.onDestroy(() => this.stopReadingTimers());
  }

  // --- loading ---------------------------------------------------------

  private loadSession(id: number): void {
    this.state.set('loading');
    this.api.session(id).then(
      (session) => this.onSessionLoaded(session),
      () => {
        this.state.set('error');
        this.errorMessage.set('This reading session could not be found.');
      },
    );
  }

  private onSessionLoaded(session: SessionOutApi): void {
    this.session.set(session);
    this.loadChatHistory(session.id);

    const screen = screenForStatus(session.status);
    if (screen === 'reading') {
      this.paragraphs = session.text.paragraphs;
      const { paragraphs, tokensById } = mapApiParagraphsToReadingText(session.text.paragraphs);
      this.tokensById = new Map(tokensById);
      this.readingText.set({ titleJapanese: session.text.title, paragraphs });
      this.selectedWordId.set(null);
      this.selectedWord.set(null);
      this.paused.set(false);
      this.startReadingTimers(session);
      this.state.set('reading');
      return;
    }

    if (screen === 'questions') {
      this.enterQuestions(session);
      return;
    }

    // 'finished'
    this.state.set('finished');
    this.api.summary(session.id).then(
      (summary) => this.summary.set(summary),
      () => {
        this.state.set('error');
        this.errorMessage.set('The summary could not be loaded.');
      },
    );
  }

  // --- reading -----------------------------------------------------------

  private startReadingTimers(session: SessionOutApi): void {
    if (this.readingTimersStarted) {
      return;
    }
    this.readingTimersStarted = true;
    this.peekedLemmas.clear();

    this.tracker = new ActiveTimeTracker(undefined, {
      activeMs: session.active_ms,
      pausedMs: session.paused_ms,
    });
    this.elapsedLabel.set(formatElapsed(session.active_ms));

    for (const eventName of ACTIVITY_EVENTS) {
      this.document.addEventListener(eventName, this.activityListener, { passive: true });
    }
    this.document.addEventListener('visibilitychange', this.visibilityListener);

    this.tickHandle = setInterval(() => {
      if (!this.tracker) {
        return;
      }
      this.tracker.tick();
      this.elapsedLabel.set(formatElapsed(this.tracker.snapshot().activeMs));
    }, TICK_INTERVAL_MS);

    this.heartbeatHandle = setInterval(() => this.sendHeartbeat(), HEARTBEAT_INTERVAL_MS);
  }

  private stopReadingTimers(): void {
    if (this.tickHandle !== null) {
      clearInterval(this.tickHandle);
      this.tickHandle = null;
    }
    if (this.heartbeatHandle !== null) {
      clearInterval(this.heartbeatHandle);
      this.heartbeatHandle = null;
    }
    if (this.readingTimersStarted) {
      for (const eventName of ACTIVITY_EVENTS) {
        this.document.removeEventListener(eventName, this.activityListener);
      }
      this.document.removeEventListener('visibilitychange', this.visibilityListener);
    }
    this.readingTimersStarted = false;
    this.tracker = null;
  }

  private onVisibilityChange(): void {
    const hidden = this.document.hidden;
    this.tracker?.setVisible(!hidden);
    if (hidden) {
      const session = this.session();
      const snapshot = this.tracker?.snapshot();
      if (session && snapshot) {
        this.api.heartbeatKeepalive(session.id, {
          active_ms: snapshot.activeMs,
          paused_ms: snapshot.pausedMs,
        });
      }
    }
  }

  private sendHeartbeat(): void {
    const session = this.session();
    const snapshot = this.tracker?.snapshot();
    if (!session || !snapshot) {
      return;
    }
    this.api
      .heartbeat(session.id, { active_ms: snapshot.activeMs, paused_ms: snapshot.pausedMs })
      .catch(() => undefined);
  }

  protected onPauseToggle(): void {
    const next = !this.paused();
    this.paused.set(next);
    this.tracker?.setPaused(next);
    this.sendHeartbeat();
  }

  protected onWordActivate(event: WordActivateEvent): void {
    this.onWordTap(event.word);
  }

  private onWordTap(word: ReadingWord): void {
    const token = this.tokensById.get(word.id);
    const session = this.session();
    if (!token || !session) {
      return;
    }
    if (!token.is_word) {
      // Particles/auxiliaries are not tappable in the text (brief).
      return;
    }

    this.selectedWordId.set(word.id);
    this.selectedWord.set({ word: token.surface, meanings: [], note: 'Loading…' });
    // A new word clears the previous one's answer and any in-flight assist
    // (its own `.then`/`.catch` below still runs, but the `selectedWordId`
    // check in each discards whatever it resolves to) -- brief: "Opening
    // another word clears the answer."
    this.wordAnswer.set(null);
    this.wordActionLoading.set(null);

    this.api.lookupWord(session.id, token.id).then(
      (result) => {
        if (this.selectedWordId() !== word.id) {
          return; // The learner moved on before this resolved.
        }
        this.selectedWord.set({
          word: result.surface,
          reading: result.reading && result.reading !== result.surface ? result.reading : undefined,
          jlptLevel: result.jlpt ? `N${result.jlpt}` : undefined,
          meanings: result.meanings,
          knownStatus: result.known_status,
          // The three LLM helps (issue #10) -- only once the lookup has
          // loaded, per the brief, so the popover never offers them
          // against a word it has not even resolved yet.
          actions: WORD_ACTIONS,
        });
      },
      () => {
        if (this.selectedWordId() === word.id) {
          this.selectedWord.set({
            word: token.surface,
            meanings: [],
            note: 'Could not look up this word.',
          });
        }
      },
    );
  }

  protected onReadingPeeked(word: ReadingWord): void {
    const token = this.tokensById.get(word.id);
    const session = this.session();
    if (!token || !session || this.peekedLemmas.has(token.lemma)) {
      return;
    }
    this.peekedLemmas.add(token.lemma);
    this.api
      .logHelp(session.id, { kind: 'reading_peek', token_id: token.id })
      .catch(() => undefined);
  }

  protected onCloseWord(): void {
    this.selectedWordId.set(null);
    this.selectedWord.set(null);
    this.wordAnswer.set(null);
    this.wordActionLoading.set(null);
  }

  /**
   * Explain word / Translate sentence / Explain grammar (issue #10) call
   * `Api.assist()` directly; "Ask tutor" (issue #11) instead opens the
   * chat panel with this word's sentence as its focus (`openChatFocusedOn`)
   * -- there is nothing to await here, so it returns immediately rather
   * than falling into the shared loading/answer plumbing below.
   */
  protected onWordAction(kind: WordActionKind): void {
    if (kind === 'tutor') {
      const tokenId = this.selectedWordId();
      this.onCloseWord();
      this.openChatFocusedOn(tokenId);
      return;
    }
    const session = this.session();
    const tokenId = this.selectedWordId();
    if (!session || !tokenId || this.wordActionLoading() !== null) {
      return; // Already loading one -- the popover disables the buttons too.
    }

    this.wordActionLoading.set(kind);
    this.api.assist(session.id, { kind, token_id: tokenId }).then(
      (result) => {
        // A request for a word the reader has since left must not touch the
        // current word's loading state or answer.
        if (this.selectedWordId() === tokenId) {
          this.wordActionLoading.set(null);
          this.wordAnswer.set({ kind: result.kind, text: result.answer });
        }
      },
      (error: unknown) => {
        if (this.selectedWordId() === tokenId) {
          this.wordActionLoading.set(null);
          // `ApiError`'s own message already reads like a sentence (e.g.
          // "The server refused: No OpenAI API key is configured.") --
          // shown in the answer block itself, never a page-level error
          // (brief, issue #10).
          const message = error instanceof ApiError ? error.message : 'This could not be answered.';
          this.wordAnswer.set({ kind, text: message, isError: true });
        }
      },
    );
  }

  // --- tutor chat (issue #11) -----------------------------------------------

  private loadChatHistory(sessionId: number): void {
    this.api.chatHistory(sessionId).then(
      (messages) =>
        this.chatMessages.set(
          messages.map((message) => ({ role: message.role, text: message.content })),
        ),
      () => undefined, // Best-effort: an empty panel on reload is an acceptable degrade.
    );
  }

  /** "Ask tutor" on a word: resolve its sentence from the already-loaded
   *  paragraphs (`sentence-for-token.ts`, a client-side mirror of the
   *  backend's own sentence splitter, used only for this chip's display
   *  text) and open the panel with it as the next question's focus. */
  private openChatFocusedOn(tokenId: string | null): void {
    if (!tokenId) {
      return;
    }
    const sentence = sentenceForToken(this.paragraphs, tokenId);
    this.chatFocusTokenId = tokenId;
    this.chatFocusLabel.set(sentence ? truncateForChip(sentence) : null);
    this.chatOpen.set(true);
  }

  protected onChatToggle(): void {
    this.chatOpen.update((open) => !open);
  }

  protected onChatFocusClear(): void {
    this.chatFocusTokenId = null;
    this.chatFocusLabel.set(null);
  }

  protected onChatSend(message: string): void {
    const session = this.session();
    if (!session || this.chatSending()) {
      return;
    }
    // The focus belongs to this one question only -- it is consumed (and
    // the chip cleared) the moment it is sent, whether or not the answer
    // itself succeeds (brief: "The next question carries that focus;
    // afterwards the chip clears").
    const focusTokenId = this.chatFocusTokenId;
    this.chatFocusTokenId = null;
    this.chatFocusLabel.set(null);

    this.chatMessages.update((messages) => [...messages, { role: 'user', text: message }]);
    this.chatSending.set(true);

    this.api
      .sendChat(session.id, { content: message, focus_token_id: focusTokenId ?? undefined })
      .then(
        (result) => {
          this.chatSending.set(false);
          this.chatMessages.update((messages) => [
            ...messages,
            { role: 'assistant', text: result.assistant_message.content },
          ]);
        },
        (error: unknown) => {
          this.chatSending.set(false);
          // Same convention as the word popover's own assist errors (issue
          // #10): `ApiError`'s message already reads like a sentence, shown
          // inline rather than as a page-level error. The question itself
          // stays in the thread (the backend kept it) -- asking again is
          // simply a new question.
          const text = error instanceof ApiError ? error.message : 'This could not be answered.';
          this.chatMessages.update((messages) => [
            ...messages,
            { role: 'assistant', text, isError: true },
          ]);
        },
      );
  }

  protected onDoneReading(): void {
    const session = this.session();
    const snapshot = this.tracker?.snapshot();
    if (!session || !snapshot) {
      return;
    }
    this.stopReadingTimers();
    this.api
      .finishReading(session.id, { active_ms: snapshot.activeMs, paused_ms: snapshot.pausedMs })
      .then(
        (updated) => this.onSessionLoaded(updated),
        () => {
          this.state.set('error');
          this.errorMessage.set('Could not finish reading. Please try again.');
        },
      );
  }

  // --- questions -----------------------------------------------------------

  private enterQuestions(session: SessionOutApi): void {
    this.totalQuestions.set(session.text.questions.length);
    this.currentQuestionIndex.set(firstUnansweredQuestionIndex(session.answers));
    this.loadCurrentQuestion(session);
    this.state.set('questions');
  }

  private loadCurrentQuestion(session: SessionOutApi): void {
    const index = this.currentQuestionIndex();
    const question = session.text.questions[index];
    const answer = session.answers[index];
    const options = question.options.map((text, optionIndex) => ({
      id: `${index}-${optionIndex}`,
      text,
    }));
    const wasAnswered = answer?.option_index !== null && answer?.option_index !== undefined;
    this.currentQuestion.set({
      id: `q${index}`,
      textEnglish: question.question,
      options,
      correctOptionId:
        wasAnswered && answer.correct_index !== null ? `${index}-${answer.correct_index}` : '',
    });
    this.selectedOptionId.set(
      wasAnswered && answer.option_index !== null ? `${index}-${answer.option_index}` : null,
    );
    this.answered.set(wasAnswered);
  }

  protected onSelectOption(optionId: string): void {
    const session = this.session();
    if (!session || this.answered()) {
      return;
    }
    const index = this.currentQuestionIndex();
    const optionIndex = Number(optionId.split('-')[1]);

    this.api.answerQuestion(session.id, { question_index: index, option_index: optionIndex }).then(
      (result) => {
        this.selectedOptionId.set(optionId);
        this.answered.set(true);
        this.currentQuestion.update((question) => ({
          ...question,
          correctOptionId: `${index}-${result.correct_index}`,
        }));
      },
      () => undefined, // A double-submit (already answered) is simply ignored.
    );
  }

  protected onNextQuestion(): void {
    const session = this.session();
    if (!session) {
      return;
    }
    const nextIndex = this.currentQuestionIndex() + 1;
    if (nextIndex >= this.totalQuestions()) {
      // That was the last question -- reload to pick up the server's own
      // transition to `finished`.
      this.loadSession(session.id);
      return;
    }
    this.currentQuestionIndex.set(nextIndex);
    this.loadCurrentQuestion(session);
  }

  // --- summary -----------------------------------------------------------

  protected summaryLookedUpWords(): readonly LookedUpWord[] {
    return this.summary()?.looked_up_words ?? [];
  }

  protected onReadAgain(): void {
    const session = this.session();
    if (!session) {
      return;
    }
    this.api.createSession(session.text.id).then(
      (next) => this.router.navigate(['/read', next.id]),
      () => undefined,
    );
  }

  protected onNewText(): void {
    this.router.navigate(['/read']);
  }

  protected onBackToSetup(): void {
    this.router.navigate(['/read']);
  }
}
