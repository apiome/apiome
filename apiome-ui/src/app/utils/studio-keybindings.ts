/**
 * Central registry for Studio keyboard shortcuts (git palette, designer, etc.).
 * Import this module when binding or documenting shortcuts — avoid scattering magic strings.
 */

export const STUDIO_GIT_PALETTE_KEY = 'g' as const;

/** Modifier: ⌘ on macOS, Ctrl on Windows/Linux (palette uses either). */
export function matchesStudioGitPaletteShortcut(ev: KeyboardEvent): boolean {
  if (ev.defaultPrevented) return false;
  if (ev.repeat) return false;
  if (ev.key?.toLowerCase() !== STUDIO_GIT_PALETTE_KEY) return false;
  if (!(ev.metaKey || ev.ctrlKey)) return false;
  if (ev.altKey || ev.shiftKey) return false;
  return true;
}

/** Toggle key for the Studio AI chatbot panel (#257). */
export const STUDIO_AI_CHATBOT_KEY = 'a' as const;

/**
 * Modifier combo for the Studio AI chatbot panel: ⌘+Shift+A on macOS, Ctrl+Shift+A on
 * Windows/Linux. Either modifier is accepted so Linux users get the same affordance.
 */
export function matchesStudioAiChatbotShortcut(ev: KeyboardEvent): boolean {
  if (ev.defaultPrevented) return false;
  if (ev.repeat) return false;
  if (ev.key?.toLowerCase() !== STUDIO_AI_CHATBOT_KEY) return false;
  if (!(ev.metaKey || ev.ctrlKey)) return false;
  if (!ev.shiftKey) return false;
  if (ev.altKey) return false;
  return true;
}

export type StudioGitPaletteActionId =
  | 'commit'
  | 'branch'
  | 'checkout'
  | 'pull'
  | 'sync'
  | 'merge'
  | 'rollback';

export type StudioGitPaletteHandlers = Partial<Record<StudioGitPaletteActionId, () => void>>;

export const STUDIO_GIT_PALETTE_ACTION_ORDER: StudioGitPaletteActionId[] = [
  'commit',
  'branch',
  'checkout',
  'pull',
  'sync',
  'merge',
  'rollback',
];

export const STUDIO_GIT_PALETTE_LABELS: Record<StudioGitPaletteActionId, { title: string; hint: string }> = {
  commit: { title: 'Commit new revision', hint: 'Create a revision from the current canvas state' },
  branch: { title: 'Create branch from here', hint: 'Branch off the current revision' },
  checkout: { title: 'Browse history / switch revision', hint: 'Open the history graph to switch revisions' },
  pull: { title: 'Switch to latest revision (pull)', hint: 'Move to the newest revision when the server is ahead' },
  sync: { title: 'Sync from default branch', hint: 'Merge default into the active branch when behind' },
  merge: { title: 'Merge branches', hint: 'Open merge dialog' },
  rollback: { title: 'Rollback to this revision', hint: 'Rollback the active branch' },
};

/** Human-readable lines for the in-palette cheatsheet (shown via Help or “?”). */
export const STUDIO_KEYBINDING_CHEATSHEET_LINES: { keys: string; description: string }[] = [
  { keys: '⌘G / Ctrl+G', description: 'Open git command palette' },
  { keys: '⌘Enter / Ctrl+Enter', description: 'Commit new revision (Designer toolbar, when available)' },
  { keys: '⌘⇧A / Ctrl+Shift+A', description: 'Toggle the AI chatbot panel on the canvas' },
  { keys: 'Esc', description: 'Close git palette' },
  { keys: '?', description: 'Toggle this cheatsheet inside the palette' },
];
