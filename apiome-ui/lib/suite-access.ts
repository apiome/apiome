/**
 * Suite Access: the per-user switch for the Designer and Developer suites (`users.suite_access`, V320).
 *
 * Both are beta / commercial products. Before this switch, the free license bundle granted the
 * `designer` flag, so every free account saw **Designer** in the Build rail and the launcher, and
 * **Developer** had no gate at all. Now an administrator turns them on per user (admin console →
 * Users → Grant Suite Access). Licenses, tenant overrides and feature-flag overrides no longer
 * decide it.
 *
 * Kept apart from `lib/db/commercial-access.ts`, a `'use server'` module, which may export only
 * async actions.
 */

import type { ExternalHomeCard, ExternalNavItem } from './external-links';

/** Destinations shown only with Suite Access: the Designer suite and the Developer suite. */
export const SUITE_ACCESS_PRODUCT_IDS: readonly string[] = ['suite', 'developer-suite'];

/** The Designer suite's built-in flags. Suite Access grants them, and its absence withholds them. */
export const SUITE_ACCESS_FLAG_NAMES: readonly string[] = ['designer', 'paths'];

/**
 * The commercial flags a user holds once Suite Access is applied.
 *
 * With access, the Designer suite's flags are added, so the suite opens whatever the license says.
 * Without it, they are removed, so no Designer link (rail, launcher, catalog preview) is built.
 * Flags a commercial host contributes (e.g. Authoring's) are left as the entitlement layer resolved them.
 *
 * @param entitledFlags Flags resolved from licenses and overrides.
 * @param suiteAccess The user's `users.suite_access`.
 * @returns The flag list to build the user's destinations from.
 */
export function applySuiteAccessToFlags(entitledFlags: readonly string[], suiteAccess: boolean): string[] {
  const others = entitledFlags.filter((flag) => !SUITE_ACCESS_FLAG_NAMES.includes(flag));
  return suiteAccess ? [...others, ...SUITE_ACCESS_FLAG_NAMES] : others;
}

/**
 * Drop the Designer and Developer suites from a user's destinations unless they have Suite Access.
 *
 * @param entries Nav items or home cards, already filtered by entitlement.
 * @param suiteAccess The user's `users.suite_access`.
 * @returns The entries the user may see.
 */
export function filterSuiteAccessEntries<T extends ExternalNavItem | ExternalHomeCard>(
  entries: readonly T[],
  suiteAccess: boolean
): T[] {
  if (suiteAccess) return [...entries];
  return entries.filter((entry) => !SUITE_ACCESS_PRODUCT_IDS.includes(entry.id));
}
