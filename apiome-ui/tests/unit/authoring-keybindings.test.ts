/**
 * Authoring keyboard shortcuts (UXE-1.2).
 *
 * Covers the acceptance criterion that Cmd/Ctrl+K and slash search are
 * keyboard complete, including the cases where they must decline.
 */

import {
  isTextEntryTarget,
  matchesAuthoringPaletteShortcut,
  matchesAuthoringSearchShortcut,
  type AuthoringKeyEvent,
} from '../../lib/authoring/keybindings';

/**
 * Build a keyboard event fixture.
 *
 * @param overrides - Fields to change.
 */
function event(overrides: Partial<AuthoringKeyEvent> & { key: string }): AuthoringKeyEvent {
  return { metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...overrides };
}

describe('matchesAuthoringPaletteShortcut', () => {
  it('accepts Cmd+K and Ctrl+K', () => {
    expect(matchesAuthoringPaletteShortcut(event({ key: 'k', metaKey: true }))).toBe(true);
    expect(matchesAuthoringPaletteShortcut(event({ key: 'k', ctrlKey: true }))).toBe(true);
  });

  it('accepts an uppercase key, as reported under some layouts', () => {
    expect(matchesAuthoringPaletteShortcut(event({ key: 'K', metaKey: true }))).toBe(true);
  });

  it('rejects a bare k, so typing is never swallowed', () => {
    expect(matchesAuthoringPaletteShortcut(event({ key: 'k' }))).toBe(false);
  });

  it('rejects extra modifiers that belong to other bindings', () => {
    expect(
      matchesAuthoringPaletteShortcut(event({ key: 'k', metaKey: true, shiftKey: true }))
    ).toBe(false);
    expect(matchesAuthoringPaletteShortcut(event({ key: 'k', ctrlKey: true, altKey: true }))).toBe(
      false
    );
  });

  it('ignores auto-repeat and already-handled events', () => {
    expect(matchesAuthoringPaletteShortcut(event({ key: 'k', metaKey: true, repeat: true }))).toBe(
      false
    );
    expect(
      matchesAuthoringPaletteShortcut(event({ key: 'k', metaKey: true, defaultPrevented: true }))
    ).toBe(false);
  });

  it('rejects other keys', () => {
    expect(matchesAuthoringPaletteShortcut(event({ key: 'j', metaKey: true }))).toBe(false);
  });
});

describe('isTextEntryTarget', () => {
  it.each(['INPUT', 'TEXTAREA', 'SELECT'])('detects a %s', (tag) => {
    expect(isTextEntryTarget(document.createElement(tag))).toBe(true);
  });

  it('detects a contenteditable element', () => {
    const div = document.createElement('div');
    div.setAttribute('contenteditable', 'true');
    // jsdom does not derive isContentEditable from the attribute.
    Object.defineProperty(div, 'isContentEditable', { value: true });
    expect(isTextEntryTarget(div)).toBe(true);
  });

  it('detects a role=textbox element used by rich editors', () => {
    const div = document.createElement('div');
    div.setAttribute('role', 'textbox');
    expect(isTextEntryTarget(div)).toBe(true);
  });

  it('does not treat ordinary elements or null as text entry', () => {
    expect(isTextEntryTarget(document.createElement('div'))).toBe(false);
    expect(isTextEntryTarget(null)).toBe(false);
  });
});

describe('matchesAuthoringSearchShortcut', () => {
  it('accepts a bare slash outside a field', () => {
    expect(
      matchesAuthoringSearchShortcut(event({ key: '/', target: document.createElement('div') }))
    ).toBe(true);
  });

  it('declines while the viewer is typing in a field', () => {
    expect(
      matchesAuthoringSearchShortcut(event({ key: '/', target: document.createElement('input') }))
    ).toBe(false);
  });

  it('declines when a modifier is held', () => {
    expect(matchesAuthoringSearchShortcut(event({ key: '/', metaKey: true }))).toBe(false);
    expect(matchesAuthoringSearchShortcut(event({ key: '/', ctrlKey: true }))).toBe(false);
  });

  it('ignores auto-repeat and already-handled events', () => {
    expect(matchesAuthoringSearchShortcut(event({ key: '/', repeat: true }))).toBe(false);
    expect(matchesAuthoringSearchShortcut(event({ key: '/', defaultPrevented: true }))).toBe(false);
  });

  it('rejects other keys', () => {
    expect(matchesAuthoringSearchShortcut(event({ key: '?' }))).toBe(false);
  });
});
