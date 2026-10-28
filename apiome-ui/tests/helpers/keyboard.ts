/**
 * Keyboard-only helpers for the jsdom suites (X3, #6224).
 *
 * A keyboard-only path is only proven when every control on it is *reached* with Tab — calling
 * `element.focus()` would skip the question of whether the control is in the tab order at all.
 * {@link tabTo} presses Tab (or Shift+Tab) until focus lands on the control, and fails with the
 * focus trail when it never does.
 */

import type userEvent from '@testing-library/user-event';

/** The `user` returned by `userEvent.setup()`. */
export type KeyboardUser = ReturnType<typeof userEvent.setup>;

/** A short name for the focused element, for a failure message. */
function describeFocus(): string {
  const el = document.activeElement as HTMLElement | null;
  if (!el || el === document.body) return 'body';
  const name = el.getAttribute('aria-label') || el.textContent?.trim().slice(0, 40) || '';
  return `${el.tagName.toLowerCase()}${name ? ` "${name}"` : ''}`;
}

/**
 * Press Tab until `target` has focus.
 *
 * @param user The user-event instance.
 * @param target The control to reach; it must be in the tab order and enabled.
 * @param options `backwards` presses Shift+Tab instead; `max` caps the presses (default 250).
 * @returns Resolves once `target` is focused.
 * @throws When `max` presses never reach `target` — the message lists where focus went.
 */
export async function tabTo(
  user: KeyboardUser,
  target: HTMLElement,
  { backwards = false, max = 250 }: { backwards?: boolean; max?: number } = {},
): Promise<void> {
  const trail: string[] = [];
  for (let press = 0; press < max; press += 1) {
    if (document.activeElement === target) return;
    await user.tab({ shift: backwards });
    trail.push(describeFocus());
  }
  if (document.activeElement === target) return;
  throw new Error(
    `Tab never reached ${target.tagName.toLowerCase()} "${
      target.getAttribute('aria-label') || target.textContent?.trim() || ''
    }" in ${max} presses. Focus went: ${trail.slice(-20).join(' → ')}`,
  );
}
