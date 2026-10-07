/**
 * Reduced-motion helpers for motion started from JavaScript (HIVE-10.2, #5338).
 *
 * `globals.css` already zeroes CSS animations and transitions when the reader asks for less
 * motion (`html[data-motion="reduce"]`, or the OS `prefers-reduced-motion`). Motion started in
 * script escapes that rule: an explicit `scrollIntoView({ behavior: 'smooth' })` outranks the
 * stylesheet's `scroll-behavior`, and a canvas camera animates for whatever duration it is
 * given. Every such call site asks these helpers instead of hard-coding the motion.
 *
 * Read from the DOM rather than from `usePreferences`, so the helpers work in any component and
 * in event handlers, wherever they are mounted.
 */

/**
 * The three durations of `docs/mockups/DESIGN.md` §3.4, in milliseconds, for motion started from
 * script. They mirror `--dur-fast` / `--dur-base` / `--dur-slow` in `globals.css`
 * (`tests/motion-pass.test.ts` keeps the two in step); nothing in the interface animates longer
 * than `slow` (HIVE-10.3, #5339).
 */
export const MOTION_MS = {
  /** Hover, toggles. */
  fast: 120,
  /** Menus, tabs. */
  base: 180,
  /** Dialogs, drawers, the rail — and the longest any motion may run. */
  slow: 260,
} as const;

/**
 * Whether motion should be suppressed right now: the stored preference (`data-motion="reduce"`
 * on `<html>`, written by the preferences boot script) or the operating system's.
 *
 * @returns `true` when the reader has asked for less motion. `false` outside a browser.
 */
export function prefersReducedMotion(): boolean {
  if (typeof document === 'undefined') return false;
  if (document.documentElement.dataset.motion === 'reduce') return true;
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/**
 * The `behavior` for `scrollIntoView` / `scrollTo`.
 *
 * @returns `'auto'` (jump) under reduced motion, otherwise `'smooth'`.
 */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? 'auto' : 'smooth';
}

/**
 * An animation duration that collapses to zero under reduced motion.
 *
 * @param milliseconds The duration to use when motion is allowed.
 * @returns `0` under reduced motion, otherwise `milliseconds`.
 */
export function motionDuration(milliseconds: number): number {
  return prefersReducedMotion() ? 0 : milliseconds;
}
