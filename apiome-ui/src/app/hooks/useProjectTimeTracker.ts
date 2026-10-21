'use client';

/**
 * Count the reader's active time on the project they have open (#544).
 *
 * While a project is selected, a heartbeat goes to the server once a {@link BEAT_INTERVAL_MS}
 * — but only when the reader is actually there: the tab is visible and they have used the page
 * (pointer, keys, wheel, scroll or touch) within {@link IDLE_AFTER_MS}. Each heartbeat the server
 * accepts credits a minute to the project for today. A tab left open over lunch, or behind other
 * windows, counts nothing.
 *
 * It is an approximation of attention, not a timesheet: reading without touching anything for
 * five minutes stops the clock until the next input.
 */

import { useEffect, useRef } from 'react';

import { recordProjectTimeForSession } from '@lib/db/project-time';

/** How often a heartbeat may be sent — the server credits this much per accepted beat. */
export const BEAT_INTERVAL_MS = 60_000;

/** How long without input before the reader counts as away. */
export const IDLE_AFTER_MS = 5 * 60_000;

/** The input that counts as the reader being there. */
const ACTIVITY_EVENTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'scroll', 'touchstart'] as const;

/** What {@link shouldBeat} weighs. */
export interface BeatState {
  /** Whether a project is open at all. */
  projectId: string | null;
  /** `document.visibilityState === 'visible'`. */
  visible: boolean;
  /** When the reader last gave input, in ms since the epoch. */
  lastActivityAt: number;
  /** Now, in ms since the epoch. */
  now: number;
}

/**
 * Whether this tick should send a heartbeat.
 *
 * @param state See {@link BeatState}.
 * @returns `true` when a project is open, the tab is visible and the reader was active recently.
 */
export function shouldBeat({ projectId, visible, lastActivityAt, now }: BeatState): boolean {
  if (!projectId || !visible) return false;
  return now - lastActivityAt <= IDLE_AFTER_MS;
}

/**
 * Send heartbeats for the open project while the reader is active.
 *
 * Opening a project counts as activity, so the first minute on it is credited even before the
 * reader touches anything. Switching projects restarts the timer for the new one.
 *
 * @param projectId The project on screen, or `null`/empty when none is.
 */
export function useProjectTimeTracker(projectId: string | null | undefined): void {
  const lastActivityAt = useRef(0);

  useEffect(() => {
    const markActive = () => {
      lastActivityAt.current = Date.now();
    };
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, markActive, { passive: true, capture: true });
    }
    document.addEventListener('visibilitychange', markActive);
    return () => {
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, markActive, { capture: true });
      }
      document.removeEventListener('visibilitychange', markActive);
    };
  }, []);

  useEffect(() => {
    if (!projectId) return;
    lastActivityAt.current = Date.now();

    const timer = window.setInterval(() => {
      const beat = shouldBeat({
        projectId,
        visible: document.visibilityState === 'visible',
        lastActivityAt: lastActivityAt.current,
        now: Date.now(),
      });
      if (beat) void recordProjectTimeForSession(projectId).catch(() => false);
    }, BEAT_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [projectId]);
}

export default useProjectTimeTracker;
