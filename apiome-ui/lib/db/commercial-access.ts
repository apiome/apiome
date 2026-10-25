'use server';

import { getAuthSession } from '../auth/server-session';
import {
  getCommercialHomeCards,
  getCommercialNavItems,
  type ExternalHomeCard,
  type ExternalNavItem,
} from '../external-links';
import { getCommercialProductFlagNames } from '../commercial-products';
import { applySuiteAccessToFlags, filterSuiteAccessEntries } from '../suite-access';
import { getEntitledFeatureFlagNames, userHasSuiteAccess } from './feature-entitlements';

export type CommercialAccessSnapshot = {
  entitledFlags: string[];
  homeCards: ExternalHomeCard[];
  navItems: ExternalNavItem[];
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
    return { entitledFlags: [], homeCards: [], navItems: [] };
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
  };
}
