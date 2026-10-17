/**
 * The Versions header's data (HIVE-11.3, #5599): the ⋯ rows, the switcher rows, the project
 * link and its chord. `versions-hive-redesign.test.tsx` covers them inside the page.
 */

import { jest } from '@jest/globals';

import {
  COPY_PROJECT_LINK_SHORTCUT,
  MERGE_NEEDS_BRANCHES,
  NEEDS_PROJECT,
  projectVersionsLink,
  versionsOverflowItems,
  versionsSwitcherItems,
  type VersionsOverflowContext,
} from '../src/app/components/ade/versions/versionsHeader';
import { gitlikeAffordance, GITLIKE_FLAG_TITLE } from '../src/app/components/ade/versions/versionsModel';
import { formatShortcutKeys, matchesShortcutChord } from '@lib/shortcuts';

/** A context with the flag on in a non-production build, a project and two branches. */
function context(over: Partial<VersionsOverflowContext> = {}): VersionsOverflowContext {
  return {
    gitlike: gitlikeAffordance(true, false),
    projectId: 'p1',
    branchCount: 2,
    exportStudioReleased: true,
    onOpenMerge: jest.fn(),
    onCopyLink: jest.fn(),
    ...over,
  };
}

const ids = (c: VersionsOverflowContext) => versionsOverflowItems(c).map((item) => item.id);
const row = (c: VersionsOverflowContext, id: string) =>
  versionsOverflowItems(c).find((item) => item.id === id)!;

describe('versionsOverflowItems', () => {
  it('lists the mockup’s rows in order, the copy link after a separator', () => {
    expect(ids(context())).toEqual(['merge', 'sunset-timeline', 'published', 'export-studio', 'copy-link']);
    expect(row(context(), 'copy-link').separatorBefore).toBe(true);
    expect(row(context(), 'sunset-timeline').href).toBe('/ade/dashboard/versions/sunset-timeline');
    expect(row(context(), 'published').href).toBe('/ade/dashboard/published');
    expect(row(context(), 'export-studio').href).toBe('/ade/dashboard/export/studio');
  });

  it('hides Merge branches in a production build without the flag, and Export studio before its release', () => {
    expect(
      ids(
        context({
          gitlike: gitlikeAffordance(false, true),
          exportStudioReleased: false,
        }),
      ),
    ).toEqual(['sunset-timeline', 'published', 'copy-link']);
  });

  it('gives Merge branches the reason it is unavailable, most fundamental first', () => {
    expect(row(context({ gitlike: gitlikeAffordance(false, false) }), 'merge').disabledReason).toBe(
      GITLIKE_FLAG_TITLE,
    );
    expect(row(context({ projectId: null }), 'merge').disabledReason).toBe(NEEDS_PROJECT);
    expect(row(context({ branchCount: 1 }), 'merge').disabledReason).toBe(MERGE_NEEDS_BRANCHES);
    expect(row(context(), 'merge').disabledReason).toBeUndefined();
  });

  it('marks Merge branches with an outline badge only where the flag is marked', () => {
    expect(row(context(), 'merge').badge).toBe('gitlike');
    expect(row(context({ gitlike: gitlikeAffordance(true, true) }), 'merge').badge).toBeUndefined();
  });

  it('wires the two commands to the page', () => {
    const c = context();
    row(c, 'merge').onSelect?.();
    row(c, 'copy-link').onSelect?.();
    expect(c.onOpenMerge).toHaveBeenCalledTimes(1);
    expect(c.onCopyLink).toHaveBeenCalledTimes(1);
  });

  it('prints the copy chord from its one declaration, and needs a project', () => {
    expect(row(context(), 'copy-link').kbd).toEqual(formatShortcutKeys(COPY_PROJECT_LINK_SHORTCUT));
    expect(row(context(), 'copy-link').kbd).toEqual(['⌘', '⇧', 'C']);
    expect(row(context({ projectId: null }), 'copy-link').disabledReason).toBe(NEEDS_PROJECT);
  });
});

describe('the copy-link chord', () => {
  const key = (init: KeyboardEventInit) => new KeyboardEvent('keydown', init);

  it('matches ⌘⇧C and Ctrl⇧C, and not ⌘C', () => {
    expect(
      matchesShortcutChord(
        key({ key: 'C', metaKey: true, shiftKey: true }),
        COPY_PROJECT_LINK_SHORTCUT.chord!,
      ),
    ).toBe(true);
    expect(
      matchesShortcutChord(
        key({ key: 'C', ctrlKey: true, shiftKey: true }),
        COPY_PROJECT_LINK_SHORTCUT.chord!,
      ),
    ).toBe(true);
    expect(matchesShortcutChord(key({ key: 'c', metaKey: true }), COPY_PROJECT_LINK_SHORTCUT.chord!)).toBe(
      false,
    );
  });
});

describe('projectVersionsLink', () => {
  it('builds an absolute, encoded link to the project’s Versions page', () => {
    expect(projectVersionsLink('https://app.apiome.dev', 'p1')).toBe(
      'https://app.apiome.dev/ade/dashboard/versions?projectId=p1',
    );
    expect(projectVersionsLink('http://x', 'a b')).toBe('http://x/ade/dashboard/versions?projectId=a%20b');
  });
});

describe('versionsSwitcherItems', () => {
  it('names each project, filters on its slug, and pills only publishable projects', () => {
    const items = versionsSwitcherItems([
      {
        id: 'p1',
        name: 'Payments API',
        slug: 'payments-api',
        publishable: true,
      },
      { id: 'c1', name: 'Claims 837P', slug: 'claims', publishable: false },
    ]);
    expect(items.map(({ id, label, keywords }) => ({ id, label, keywords }))).toEqual([
      { id: 'p1', label: 'Payments API', keywords: 'payments-api' },
      { id: 'c1', label: 'Claims 837P', keywords: 'claims' },
    ]);
    expect(items[0].leading).toBeTruthy();
    expect(items[1].leading).toBeUndefined();
  });
});
