/**
 * Authoring keyboard shortcuts (UXE-1.2).
 *
 * `Cmd/Ctrl+K` opens the command palette; `/` focuses contextual search.
 * Matching lives here, away from React, so both bindings are unit-testable and
 * cannot drift between the components that install them.
 */

/** Key that opens the command palette, combined with Cmd or Ctrl. */
export const AUTHORING_PALETTE_KEY = 'k';

/** Key that focuses contextual search, pressed on its own. */
export const AUTHORING_SEARCH_KEY = '/';

/** The subset of `KeyboardEvent` these matchers read. */
export type AuthoringKeyEvent = {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  repeat?: boolean;
  defaultPrevented?: boolean;
  target?: EventTarget | null;
};

/**
 * True when the event should open the command palette.
 *
 * Requires exactly one of Cmd/Ctrl and rejects Alt/Shift, so it cannot swallow
 * a browser or OS binding the viewer meant to use. Auto-repeat and already
 * handled events are ignored.
 *
 * @param event - Keyboard event to test.
 */
export function matchesAuthoringPaletteShortcut(event: AuthoringKeyEvent): boolean {
  if (event.defaultPrevented || event.repeat) return false;
  if (event.altKey || event.shiftKey) return false;
  if (!event.metaKey && !event.ctrlKey) return false;
  return event.key.toLowerCase() === AUTHORING_PALETTE_KEY;
}

/**
 * True when an element already consumes plain typing, so a bare `/` must be
 * left alone.
 *
 * Covers inputs, textareas, selects and anything marked `contenteditable`,
 * plus the `role="textbox"` used by rich editors that are not native fields.
 *
 * @param target - Event target to inspect.
 */
export function isTextEntryTarget(target: EventTarget | null | undefined): boolean {
  if (!target || typeof (target as Element).tagName !== 'string') return false;
  const element = target as HTMLElement;
  const tag = element.tagName.toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (element.isContentEditable) return true;
  return element.getAttribute?.('role') === 'textbox';
}

/**
 * True when the event should move focus to contextual search.
 *
 * A bare `/` is an ordinary character, so this deliberately declines whenever
 * the viewer is typing into a field or holding a modifier.
 *
 * @param event - Keyboard event to test.
 */
export function matchesAuthoringSearchShortcut(event: AuthoringKeyEvent): boolean {
  if (event.defaultPrevented || event.repeat) return false;
  if (event.metaKey || event.ctrlKey || event.altKey) return false;
  if (event.key !== AUTHORING_SEARCH_KEY) return false;
  return !isTextEntryTarget(event.target);
}

/** Human-readable shortcut hints, for tooltips and the palette footer. */
export const AUTHORING_SHORTCUT_HINTS = [
  { keys: '⌘K / Ctrl+K', action: 'Open the command palette' },
  { keys: '/', action: 'Search this surface' },
  { keys: 'Esc', action: 'Close the palette' },
] as const;
