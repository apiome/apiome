'use client';

import * as React from 'react';

/** Props for {@link CountUp}. */
export interface CountUpProps {
  /** The number to settle on. Drawn as its locale string for assistive technology. */
  value: number;
}

/**
 * A number that counts up to its value once, as the page lands (facelift "motion",
 * PROPOSALS_FACELIFT.md §2): a stat arrives rather than snaps.
 *
 * The count is CSS, not script: the figure is a registered custom property (`--count-figure`)
 * that `[data-count-figure]::before` prints through a counter. The element carries its real
 * value from the first render; a `@starting-style` block in globals.css gives the property a
 * starting value of zero, so the transition on it — one `--dur-slow`, eased out — runs the
 * figure up as the element enters. So the real value is in the DOM from the first frame (also
 * visually hidden, which is what a screen reader, a test and a fixture dump read), nothing
 * re-renders while it counts, the Reduce motion blocks zero it like any other transition, and a
 * browser without `@property` or `@starting-style` simply prints the number.
 *
 * @param props See {@link CountUpProps}.
 * @returns The figure.
 */
export function CountUp({ value }: CountUpProps) {
  const rounded = Number.isFinite(value) ? Math.round(value) : 0;

  return (
    <span className="hive-stat__figure" data-count={rounded}>
      {/* The counter is drawn by `[data-count-figure]::before` (globals.css); the property it
          prints starts at 0 (`@starting-style`) and transitions to this value. */}
      <span
        data-count-figure=""
        aria-hidden
        style={{ '--count-figure': rounded } as React.CSSProperties}
      />
      <span className="sr-only">{rounded.toLocaleString()}</span>
    </span>
  );
}

export default CountUp;
