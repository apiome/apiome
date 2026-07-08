'use server';

import { getAuthSession } from '../auth/server-session';
import {
  getCommercialHomeCards,
  getCommercialNavItems,
  type ExternalHomeCard,
  type ExternalNavItem,
} from '../external-links';
import { COMMERCIAL_PRODUCT_FLAG_NAMES } from '../commercial-products';
import { getEntitledFeatureFlagNames } from './feature-entitlements';

export type CommercialAccessSnapshot = {
  entitledFlags: string[];
  homeCards: ExternalHomeCard[];
  navItems: ExternalNavItem[];
};

/** Licensed commercial products for the signed-in user (home grid + top nav). */
export async function getCommercialAccessForSession(): Promise<CommercialAccessSnapshot> {
  const session = await getAuthSession();
  const user = session?.user as { user_id?: string; current_tenant_id?: string } | undefined;
  const userId = user?.user_id;
  const tenantId = user?.current_tenant_id ?? null;

  if (!userId) {
    return { entitledFlags: [], homeCards: [], navItems: [] };
  }

  const entitledFlags = await getEntitledFeatureFlagNames(
    userId,
    tenantId,
    [...COMMERCIAL_PRODUCT_FLAG_NAMES]
  );
  const flagSet = new Set(entitledFlags);

  return {
    entitledFlags,
    homeCards: getCommercialHomeCards(flagSet),
    navItems: getCommercialNavItems(flagSet),
  };
}
