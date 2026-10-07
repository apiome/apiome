/**
 * The keyboard guide stays in step with the shortcut registry — HIVE-10.2 (#5338).
 *
 * `docs/guide/keyboard.md` documents the keyboard path for every primary task and ends with the
 * full shortcut reference. That table is written from `lib/shortcuts.ts`; this suite fails when a
 * shortcut is declared there without a row in the guide, or its chord is spelled differently.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  CLOSE_OVERLAY_SHORTCUT,
  DATA_TABLE_SHORTCUTS,
  JUMP_SHORTCUTS,
  LIST_ACTION_SHORTCUTS,
  PALETTE_SHORTCUT,
  PREFERENCES_SHORTCUT,
  RAIL_SHORTCUT,
  SEARCH_SHORTCUT,
  SHORTCUT_DISPLAY_ORDER,
  SHORTCUT_SHEET_SHORTCUT,
  spellShortcut,
  type ShortcutDefinition,
} from '../lib/shortcuts';

const GUIDE = fs.readFileSync(path.join(__dirname, '..', '..', 'docs', 'guide', 'keyboard.md'), 'utf8');

/** Every shortcut the shell declares. */
const DECLARED: ShortcutDefinition[] = [
  PALETTE_SHORTCUT,
  SEARCH_SHORTCUT,
  PREFERENCES_SHORTCUT,
  RAIL_SHORTCUT,
  SHORTCUT_SHEET_SHORTCUT,
  CLOSE_OVERLAY_SHORTCUT,
  ...JUMP_SHORTCUTS,
  ...LIST_ACTION_SHORTCUTS,
  ...DATA_TABLE_SHORTCUTS,
];

/** The reference table's rows: `| \`chord\` | does | where |`. */
const ROWS = GUIDE.slice(GUIDE.indexOf('## Shortcut reference'))
  .split('\n')
  .filter((line) => line.startsWith('| `'));

describe('docs/guide/keyboard.md', () => {
  it('covers every shortcut the display order knows', () => {
    // A new declaration is added to SHORTCUT_DISPLAY_ORDER; if it is not in DECLARED either, this
    // suite cannot see it — so the two must agree.
    expect(DECLARED.map((definition) => definition.id).sort()).toEqual([...SHORTCUT_DISPLAY_ORDER].sort());
  });

  it.each(DECLARED.map((definition) => [definition.id, definition] as const))(
    'has a reference row for %s with its chord and description',
    (_id, definition) => {
      const row = ROWS.find((line) => line.startsWith(`| \`${spellShortcut(definition)}\` |`));
      expect(row).toBeDefined();
      expect(row).toContain(`| ${definition.description} |`);
    },
  );

  it('has no reference row the registry does not declare', () => {
    expect(ROWS).toHaveLength(DECLARED.length);
  });

  it.each([
    'Sign in',
    'Find anything',
    'Go to a section',
    'Switch workspace',
    'Browse, filter and act on a table',
    'Create something',
    'Import a specification',
    'Cut, publish or export a version',
    'Edit roles in the permission matrix',
    'Manage members and API keys',
    'Set preferences',
  ])('documents the keyboard path for “%s”', (task) => {
    expect(GUIDE).toMatch(new RegExp(`^### ${task.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'm'));
  });
});
