/** A clock the tracker reads from when the caller does not pass an
 *  explicit timestamp -- injectable so tests can drive it with plain
 *  numbers instead of real timers (`performance.now()`/`Date.now()` in
 *  production, an incrementing counter in `active-time-tracker.spec.ts`). */
export interface ActiveTimeTrackerClock {
  now(): number;
}

export const DEFAULT_CLOCK: ActiveTimeTrackerClock = { now: () => Date.now() };

/** No pointer, key, scroll, touch or wheel activity for this long -> idle
 *  (brief). */
export const IDLE_TIMEOUT_MS = 60_000;

export interface ActiveTimeTrackerState {
  activeMs: number;
  pausedMs: number;
}

/**
 * Tracks a reading session's active/paused time (issue #9's brief): active
 * time counts only while the reader is not paused, the document is
 * visible, and the reader is not idle; a manual pause counts into
 * `pausedMs` instead, while a hidden document or an idle stretch is simply
 * not counted into either -- it is lost real time, on purpose (see the
 * module's own reasoning in `CLAUDE.md`'s "Frontend" section once this
 * lands).
 *
 * Deliberately has no timer of its own: every method takes (or defaults)
 * an explicit timestamp and settles the elapsed time against it, so the
 * host decides *when* to call in (a periodic tick for the live elapsed
 * label, real DOM listeners for pause/visibility/activity) and tests can
 * drive it with plain incrementing numbers, no fake timers required.
 */
export class ActiveTimeTracker {
  private activeMs: number;
  private pausedMs: number;
  private paused = false;
  private visible = true;
  private lastSettledAt: number;
  private lastActivityAt: number;

  constructor(
    private readonly clock: ActiveTimeTrackerClock = DEFAULT_CLOCK,
    initial: Partial<ActiveTimeTrackerState> & { now?: number } = {},
  ) {
    const now = initial.now ?? this.clock.now();
    this.activeMs = initial.activeMs ?? 0;
    this.pausedMs = initial.pausedMs ?? 0;
    this.lastSettledAt = now;
    this.lastActivityAt = now;
  }

  /**
   * Settle elapsed time since the last call into `activeMs`/`pausedMs`/
   * neither, based on the state that held over the just-elapsed interval.
   * Every other method calls this first, so reading a value is always up
   * to date and no caller has to remember to tick separately -- except
   * that a host still *should* call it periodically (e.g. every second)
   * purely so an idle timeout is ever detected without a fresh DOM event
   * arriving to trigger it.
   *
   * `paused`/`visible` cannot change *during* one `tick()` call -- both
   * only ever change through their own setters, which call `tick()` first
   * -- but idle can: nothing calls in when the reader simply stops
   * touching anything, so a single `tick()` spanning the idle threshold
   * has to split its own interval at `lastActivityAt + IDLE_TIMEOUT_MS`
   * rather than only checking idle-ness at the interval's start.
   */
  tick(now: number = this.clock.now()): void {
    const start = this.lastSettledAt;
    if (now > start) {
      if (this.paused) {
        this.pausedMs += now - start;
      } else if (!this.visible) {
        // Hidden: not paused, but not counted either -- lost real time.
      } else {
        const idleAt = this.lastActivityAt + IDLE_TIMEOUT_MS;
        const activeUntil = Math.min(now, Math.max(start, idleAt));
        this.activeMs += activeUntil - start;
        // [activeUntil, now), if non-empty, is the idle stretch -- also
        // not counted (brief: "the idle stretch is not counted").
      }
    }
    this.lastSettledAt = now;
  }

  setPaused(paused: boolean, now: number = this.clock.now()): void {
    this.tick(now);
    this.paused = paused;
    if (!paused) {
      this.lastActivityAt = now;
    }
  }

  setVisible(visible: boolean, now: number = this.clock.now()): void {
    this.tick(now);
    this.visible = visible;
    if (visible) {
      this.lastActivityAt = now;
    }
  }

  /** Pointer, key, scroll, touch or wheel activity -- resumes from idle
   *  without counting the idle stretch itself (brief). */
  noteActivity(now: number = this.clock.now()): void {
    this.tick(now);
    this.lastActivityAt = now;
  }

  isPaused(): boolean {
    return this.paused;
  }

  snapshot(now: number = this.clock.now()): ActiveTimeTrackerState {
    this.tick(now);
    return { activeMs: this.activeMs, pausedMs: this.pausedMs };
  }
}
