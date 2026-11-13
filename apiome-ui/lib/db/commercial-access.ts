'use server';

import { getAuthSession } from '../auth/server-session';
import {
  getCommercialHomeCards,
  getCommercialNavItems,
  type ExternalHomeCard,
  type ExternalNavItem,
} from '../external-links';
import { getStudioAppUrl } from '../app-urls';
import { getCommercialProductFlagNames } from '../commercial-products';
import {
  applySuiteAccessToFlags,
  filterSuiteAccessEntries,
  SUITE_ACCESS_FLAG_NAMES,
} from '../suite-access';
import { getEntitledFeatureFlagNames, userHasSuiteAccess } from './feature-entitlements';

export type CommercialAccessSnapshot = {
  entitledFlags: string[];
  homeCards: ExternalHomeCard[];
  navItems: ExternalNavItem[];
  /**
   * Where the rail's **Suite** link (under Home) points, or `null` when the user is not
   * entitled to the commercial suite. The suite is a separate, commercially licensed
   * application that is not part of this open-source project; this repository only links to it.
   */
  suiteHref: string | null;
};

/**
 * Licensed commercial products for the signed-in user (home grid + top nav).
 *
 * The Designer and Developer suites also need the user's Suite Access (`users.suite_access`,
 * see `lib/suite-access.ts`); a license alone no longer shows them.
 */
export async function getCommercialAccessForSession(): Promise<CommercialAccessSnapshot> {
  const session = await getAuthSession();
  const user = session?.user as { user_id?: string; current_tenant_id?: string } | undefined;
  const userId = user?.user_id;
  const tenantId = user?.current_tenant_id ?? null;

  if (!userId) {
    return { entitledFlags: [], homeCards: [], navItems: [], suiteHref: null };
  }

  const [licensedFlags, suiteAccess] = await Promise.all([
    getEntitledFeatureFlagNames(userId, tenantId, getCommercialProductFlagNames()),
    userHasSuiteAccess(userId),
  ]);
  const entitledFlags = applySuiteAccessToFlags(licensedFlags, suiteAccess);
  const flagSet = new Set(entitledFlags);

  return {
    entitledFlags,
    homeCards: filterSuiteAccessEntries(getCommercialHomeCards(flagSet), suiteAccess),
    navItems: filterSuiteAccessEntries(getCommercialNavItems(flagSet), suiteAccess),
    suiteHref: SUITE_ACCESS_FLAG_NAMES.some((flag) => flagSet.has(flag)) ? getStudioAppUrl() : null,
  };
}
