import { describe, expect, it } from 'vitest';
import { ActiveTimeTracker, IDLE_TIMEOUT_MS } from './active-time-tracker';

describe('ActiveTimeTracker', () => {
  it('counts plain elapsed time as active while nothing else is going on', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    tracker.tick(1000);
    expect(tracker.snapshot(1000)).toEqual({ activeMs: 1000, pausedMs: 0 });
  });

  it('counts a manual pause into pausedMs, not activeMs', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    // [0,1000) is active (nothing paused it yet); pausing at 1000 only
    // affects what comes after.
    tracker.setPaused(true, 1000);
    tracker.tick(3000);
    expect(tracker.snapshot(3000)).toEqual({ activeMs: 1000, pausedMs: 2000 });
  });

  it('resuming from a manual pause counts active time again', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    tracker.setPaused(true, 1000); // paused [0,1000) is active -> +1000 active
    tracker.setPaused(false, 2000); // paused [1000,2000) -> +1000 paused
    tracker.tick(4000); // active [2000,4000) -> +2000 active
    expect(tracker.snapshot(4000)).toEqual({ activeMs: 3000, pausedMs: 1000 });
  });

  it('a hidden document does not count toward active or paused time', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    tracker.setVisible(false, 1000); // [0,1000) active -> +1000
    tracker.tick(5000); // [1000,5000) hidden -> counted nowhere
    expect(tracker.snapshot(5000)).toEqual({ activeMs: 1000, pausedMs: 0 });
  });

  it('becoming visible again resumes counting active time', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    tracker.setVisible(false, 1000);
    tracker.setVisible(true, 5000);
    tracker.tick(6000);
    expect(tracker.snapshot(6000)).toEqual({ activeMs: 2000, pausedMs: 0 });
  });

  it('an idle stretch (no activity for IDLE_TIMEOUT_MS) stops counting active time', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    // No activity at all after t=0: idle starts at IDLE_TIMEOUT_MS.
    tracker.tick(IDLE_TIMEOUT_MS + 10_000);
    expect(tracker.snapshot(IDLE_TIMEOUT_MS + 10_000)).toEqual({
      activeMs: IDLE_TIMEOUT_MS,
      pausedMs: 0,
    });
  });

  it('activity resumes counting without retroactively counting the idle stretch', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    const idleEndsAt = IDLE_TIMEOUT_MS + 5000;
    tracker.tick(idleEndsAt); // active up to 60_000, idle for the rest
    tracker.noteActivity(idleEndsAt); // resumes counting from here
    tracker.tick(idleEndsAt + 2000);
    const snapshot = tracker.snapshot(idleEndsAt + 2000);
    expect(snapshot.activeMs).toBe(IDLE_TIMEOUT_MS + 2000);
    expect(snapshot.pausedMs).toBe(0);
  });

  it('activity before the idle threshold never triggers idle at all', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    tracker.noteActivity(30_000);
    tracker.tick(50_000);
    expect(tracker.snapshot(50_000)).toEqual({ activeMs: 50_000, pausedMs: 0 });
  });

  it('idle time while manually paused is already excluded by the pause, not double-subtracted', () => {
    const tracker = new ActiveTimeTracker(undefined, { now: 0 });
    tracker.setPaused(true, 0);
    tracker.tick(IDLE_TIMEOUT_MS + 60_000);
    // Paused the whole time -- goes to pausedMs regardless of the idle rule,
    // since `isCounting` already excludes a manual pause first.
    expect(tracker.snapshot(IDLE_TIMEOUT_MS + 60_000)).toEqual({
      activeMs: 0,
      pausedMs: IDLE_TIMEOUT_MS + 60_000,
    });
  });

  it('restores initial active/paused ms so a reloaded session resumes correctly', () => {
    const tracker = new ActiveTimeTracker(undefined, { activeMs: 42_000, pausedMs: 7000, now: 0 });
    tracker.tick(1000);
    expect(tracker.snapshot(1000)).toEqual({ activeMs: 43_000, pausedMs: 7000 });
  });

  it('uses the injected clock when no explicit timestamp is passed', () => {
    let now = 1000;
    const tracker = new ActiveTimeTracker({ now: () => now });
    now = 4000;
    expect(tracker.snapshot()).toEqual({ activeMs: 3000, pausedMs: 0 });
  });
});
