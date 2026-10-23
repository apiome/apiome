/**
 * Which rail nav groups the reader has folded away (HIVE-3.1, #5287).
 *
 * `DESIGN.md` §5.2 makes the group headings click-to-collapse, and the mockup persists the
 * choice under `hive.navCollapsed` — the same `hive.*` device-local vocabulary the
 * preferences of HIVE-1.3 use, but deliberately *not* a preference: it is a per-group
 * scratch state with no pane row, no `<html>` attribute and no CSS to drive.
 *
 * Groups are stored by **id** (`build`, `bring-in`, …) rather than by heading, so renaming
 * a heading does not silently unfold a group the reader had put away. Every function here
 * tolerates a hostile store: a browser with storage disabled, a value written by another
 * build, or a string that is not JSON at all. The rail always renders; at worst it renders
 * with the model's default folds.
 *
 * **First run (HIVE-12.1, #5608).** A reader who has never folded or unfolded a group has
 * no stored value, and gets the groups the model marks `defaultCollapsed` (Workspace).
 * Nothing is written until they click a heading; from then on the stored list — even an
 * empty one — is their choice and the defaults no longer apply.
 */

import {
  PLATFORM_NAV_GROUPS,
  type PlatformNavGroup,
  type PlatformNavGroupId,
} from '@lib/platform-nav';

/** Storage key, as `DESIGN.md` §5.2 and `docs/mockups/assets/hive.js` spell it. */
export const NAV_COLLAPSED_STORAGE_KEY = 'hive.navCollapsed';

/**
 * The groups that start folded before the reader has made a choice.
 *
 * @param groups The nav model, or the resolved groups the rail renders.
 * @returns Ids of the labelled groups marked `defaultCollapsed`, in model order.
 */
export function defaultCollapsedNavGroups(
  groups: readonly Pick<PlatformNavGroup, 'id' | 'label' | 'defaultCollapsed'>[] = PLATFORM_NAV_GROUPS
): PlatformNavGroupId[] {
  // An unlabelled group has no heading to unfold it with, so it never starts folded.
  return groups.filter((group) => group.defaultCollapsed && group.label).map((group) => group.id);
}

/**
 * Read the folded groups.
 *
 * @param groups The nav model the defaults come from; the shipped model unless a caller
 *               (the rail, a test) passes its own.
 * @returns The reader's stored group ids. When there is no stored choice — nothing stored
 *          yet, a store that cannot be read, or a value that is not a list — the groups
 *          the model marks `defaultCollapsed` instead.
 */
export function readCollapsedNavGroups(
  groups: readonly Pick<PlatformNavGroup, 'id' | 'label' | 'defaultCollapsed'>[] = PLATFORM_NAV_GROUPS
): PlatformNavGroupId[] {
  const defaults = defaultCollapsedNavGroups(groups);
  if (typeof window === 'undefined') return defaults;

  try {
    const raw = window.localStorage.getItem(NAV_COLLAPSED_STORAGE_KEY);
    if (raw === null) return defaults;

    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return defaults;

    return parsed.filter((entry): entry is PlatformNavGroupId => typeof entry === 'string');
  } catch {
    return defaults;
  }
}

/**
 * Persist the folded groups.
 *
 * A failure is swallowed on purpose: Safari's private mode throws on every write, and a
 * rail that cannot remember a folded group is still a working rail.
 *
 * @param groupIds Group ids that should render folded.
 */
export function writeCollapsedNavGroups(groupIds: readonly PlatformNavGroupId[]): void {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, JSON.stringify([...groupIds]));
  } catch {
    /* Storage unavailable — the fold lasts for this page view only. */
  }
}

/**
 * Fold or unfold one group.
 *
 * @param groupIds The currently folded ids.
 * @param groupId The group whose heading was clicked.
 * @returns A new list with `groupId` added when it was open, removed when it was folded.
 */
export function toggleCollapsedNavGroup(
  groupIds: readonly PlatformNavGroupId[],
  groupId: PlatformNavGroupId
): PlatformNavGroupId[] {
  return groupIds.includes(groupId)
    ? groupIds.filter((id) => id !== groupId)
    : [...groupIds, groupId];
}
