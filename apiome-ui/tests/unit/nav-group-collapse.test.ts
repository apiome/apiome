/**
 * The rail's folded-group store (HIVE-3.1) and its first-run defaults (HIVE-12.1, #5608).
 *
 * A reader with nothing stored gets the groups the model marks `defaultCollapsed`; once
 * anything is stored under `hive.navCollapsed` — even an empty list — that is their choice.
 */
import { PLATFORM_NAV_GROUPS, type PlatformNavGroup } from '../../lib/platform-nav';
import {
  NAV_COLLAPSED_STORAGE_KEY,
  defaultCollapsedNavGroups,
  readCollapsedNavGroups,
  toggleCollapsedNavGroup,
  writeCollapsedNavGroups,
} from '../../src/app/components/shell/navGroupCollapse';

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe('the nav model', () => {
  it('folds Workspace by default and leaves the daily-work groups open', () => {
    const folded = PLATFORM_NAV_GROUPS.filter((group) => group.defaultCollapsed).map((group) => group.id);
    expect(folded).toEqual(['workspace']);
  });
});

describe('defaultCollapsedNavGroups', () => {
  it('reads the shipped model when given nothing', () => {
    expect(defaultCollapsedNavGroups()).toEqual(['workspace']);
  });

  it('never folds an unlabelled group, which has no heading to unfold it', () => {
    const groups: Pick<PlatformNavGroup, 'id' | 'label' | 'defaultCollapsed'>[] = [
      { id: 'home', defaultCollapsed: true },
      { id: 'build', label: 'Build', defaultCollapsed: true },
      { id: 'ship', label: 'Ship' },
    ];
    expect(defaultCollapsedNavGroups(groups)).toEqual(['build']);
  });
});

describe('readCollapsedNavGroups', () => {
  it('seeds from the model on first run', () => {
    expect(readCollapsedNavGroups()).toEqual(['workspace']);
  });

  it('seeds from the groups it is given', () => {
    expect(readCollapsedNavGroups([{ id: 'ship', label: 'Ship', defaultCollapsed: true }])).toEqual([
      'ship',
    ]);
  });

  it('keeps a stored choice instead of the defaults', () => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, JSON.stringify(['govern']));
    expect(readCollapsedNavGroups()).toEqual(['govern']);
  });

  it('treats a stored empty list as "nothing folded", not as first run', () => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, '[]');
    expect(readCollapsedNavGroups()).toEqual([]);
  });

  it.each([
    ['an object', '{"build":true}'],
    ['not JSON', 'not json'],
    ['an empty string', ''],
  ])('falls back to the defaults for %s', (_label, raw) => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, raw);
    expect(readCollapsedNavGroups()).toEqual(['workspace']);
  });

  it('keeps only the strings of a mixed list', () => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, JSON.stringify(['ship', 3, null]));
    expect(readCollapsedNavGroups()).toEqual(['ship']);
  });

  it('falls back to the defaults when storage cannot be read', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(readCollapsedNavGroups()).toEqual(['workspace']);
  });
});

describe('writing and toggling', () => {
  it('round-trips through the same key', () => {
    writeCollapsedNavGroups(['build', 'workspace']);
    expect(window.localStorage.getItem(NAV_COLLAPSED_STORAGE_KEY)).toBe('["build","workspace"]');
    expect(readCollapsedNavGroups()).toEqual(['build', 'workspace']);
  });

  it('unfolds the default group on its first toggle', () => {
    expect(toggleCollapsedNavGroup(readCollapsedNavGroups(), 'workspace')).toEqual([]);
  });

  it('swallows a write that storage refuses', () => {
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    expect(() => writeCollapsedNavGroups(['build'])).not.toThrow();
  });
});
