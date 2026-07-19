/**
 * Authoring shortcut preferences (UXE-1.2).
 *
 * The bare `/` shortcut is a single-character shortcut, so WCAG 2.2 SC 2.1.4
 * requires a way to switch it off. These cover that mechanism.
 */

import {
  AUTHORING_SHORTCUTS_CHANGED_EVENT,
  isSlashSearchEnabled,
  setSlashSearchEnabled,
} from '../../lib/authoring/shortcut-preferences';

beforeEach(() => {
  window.localStorage.clear();
});

describe('isSlashSearchEnabled', () => {
  it('defaults to enabled, so the shortcut works without configuration', () => {
    expect(isSlashSearchEnabled()).toBe(true);
  });

  it('is disabled only by an explicit opt-out', () => {
    setSlashSearchEnabled(false);
    expect(isSlashSearchEnabled()).toBe(false);
  });

  it('can be turned back on', () => {
    setSlashSearchEnabled(false);
    setSlashSearchEnabled(true);
    expect(isSlashSearchEnabled()).toBe(true);
  });

  it('stays enabled when storage holds an unrecognized value', () => {
    window.localStorage.setItem('authoring.shortcuts.slashSearch', 'maybe');
    expect(isSlashSearchEnabled()).toBe(true);
  });

  it('stays enabled when storage is unreadable, rather than silently dying', () => {
    const getItem = jest
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('denied');
      });

    expect(isSlashSearchEnabled()).toBe(true);
    getItem.mockRestore();
  });
});

describe('setSlashSearchEnabled', () => {
  it('returns the value now in effect', () => {
    expect(setSlashSearchEnabled(false)).toBe(false);
    expect(setSlashSearchEnabled(true)).toBe(true);
  });

  it('announces the change so open views re-read it', () => {
    const listener = jest.fn();
    window.addEventListener(AUTHORING_SHORTCUTS_CHANGED_EVENT, listener);

    setSlashSearchEnabled(false);

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTHORING_SHORTCUTS_CHANGED_EVENT, listener);
  });

  it('still reports the intended value when storage refuses the write', () => {
    const setItem = jest
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('quota');
      });

    expect(setSlashSearchEnabled(false)).toBe(false);
    setItem.mockRestore();
  });
});
