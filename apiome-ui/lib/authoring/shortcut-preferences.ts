/**
 * Keyboard shortcut preferences for the Authoring shell (UXE-1.2).
 *
 * `Cmd/Ctrl+K` is a modifier chord and needs no opt-out. The bare `/` search
 * shortcut is a single-character shortcut, and WCAG 2.2 SC 2.1.4 (Character Key
 * Shortcuts, Level A) requires that such a shortcut can be turned off, remapped
 * or limited to on-focus. Without that, a speech-input user — or anyone whose
 * assistive technology emits stray keystrokes — has focus pulled away with no
 * recourse. This module provides the "turn off" mechanism.
 *
 * The preference is per browser rather than per tenant: it describes how the
 * person types, not what they are working on.
 */

/** Storage key for the slash-search preference. */
const SLASH_SEARCH_KEY = 'authoring.shortcuts.slashSearch';

/** Event dispatched when the preference changes, so open views re-read it. */
export const AUTHORING_SHORTCUTS_CHANGED_EVENT = 'authoring:shortcuts-changed';

/**
 * Whether the bare `/` search shortcut is enabled.
 *
 * Defaults to enabled, so the shortcut works without configuration; only an
 * explicit opt-out disables it.
 *
 * @returns True when `/` should focus contextual search.
 */
export function isSlashSearchEnabled(): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return window.localStorage.getItem(SLASH_SEARCH_KEY) !== 'off';
  } catch {
    // A storage denial must not disable a working shortcut.
    return true;
  }
}

/**
 * Turn the bare `/` search shortcut on or off.
 *
 * @param enabled - True to enable the shortcut.
 * @returns The value now in effect.
 */
export function setSlashSearchEnabled(enabled: boolean): boolean {
  if (typeof window === 'undefined') return enabled;
  try {
    window.localStorage.setItem(SLASH_SEARCH_KEY, enabled ? 'on' : 'off');
  } catch {
    /* ignore — the in-memory result below still applies for this view */
  }
  window.dispatchEvent(new Event(AUTHORING_SHORTCUTS_CHANGED_EVENT));
  return enabled;
}
