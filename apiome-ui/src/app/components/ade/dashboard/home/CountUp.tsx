'use client';

/**
 * `<CountUp>` — a figure that rises to its value on first paint (HIVE-14, PROPOSALS.md §5.2.6).
 *
 * Home's six counters are the first numbers a reader sees after sign-in; 640 ms of counting up
 * is what makes them read as *measurements* rather than as a row of labels. Three things keep
 * it honest:
 *
 * - The first render is the final value. Server markup, a reader with motion reduced, and a
 *   test that reads the figure all see the number itself; the animation is an effect that
 *   starts afterwards and only when motion is allowed.
 * - Motion is allowed by the same two switches the rest of the app reads — the Preferences
 *   pane's `data-motion="reduce"` and the OS's `prefers-reduced-motion` — so a reader who asked
 *   for stillness gets a still number.
 * - Under Jest the animation never starts: a suite asserting the figure would otherwise race a
 *   requestAnimationFrame loop, and jsdom has nothing to show it to.
 */

import * as React from 'react';

/** How long the count takes — a little over `--dur-slow`, so a four-digit figure is readable. */
const DURATION_MS = 640;

/**
 * Whether the reader has asked for motion.
 *
 * @returns False on the server, under reduced motion (either switch), and under Jest.
 */
export function countUpAllowed(): boolean {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false;
  if (process.env.NODE_ENV === 'test') return false;
  if (document.documentElement.getAttribute('data-motion') === 'reduce') return false;
  return !(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
}

export interface CountUpProps {
  /** The figure to arrive at. */
  value: number;
  /** How to print a figure. Defaults to the bare number, which is how the strip has always printed it. */
  format?: (value: number) => string;
}

/**
 * Render a number that counts up to `value` once, eased out.
 *
 * @param props See {@link CountUpProps}.
 * @returns The figure as text.
 */
export function CountUp({ value, format = String }: CountUpProps) {
  const [shown, setShown] = React.useState(value);

  React.useEffect(() => {
    if (!countUpAllowed() || !Number.isFinite(value) || value === 0) {
      setShown(value);
      return undefined;
    }

    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / DURATION_MS);
      const eased = 1 - Math.pow(1 - progress, 3);
      setShown(Math.round(value * eased));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };

    setShown(0);
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return <>{format(shown)}</>;
}

export default CountUp;
