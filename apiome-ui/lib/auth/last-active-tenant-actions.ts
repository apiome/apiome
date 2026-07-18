'use server';

/**
 * Client-callable write side of the last-active-tenant cookie (OLO-6.1, #4218).
 *
 * Called by the tenant switcher right after a successful
 * `useSession().update({ current_tenant_id })` so the choice survives the
 * session JWT and can seed the next login's active tenant (OLO-3.3 routing).
 *
 * Misuse safeguards: only runs for an authenticated session, and only accepts
 * a well-formed tenant id — and even then the value is just a login *candidate*
 * that `pickActiveTenantId` re-validates against live memberships.
 */

import { cookies } from 'next/headers';
// Imported via the alias so the jest `auth/server-session` mock mapping applies.
import { getAuthSession } from '@lib/auth/server-session';
import {
  LAST_ACTIVE_TENANT_COOKIE,
  LAST_ACTIVE_TENANT_MAX_AGE_SECONDS,
  isWellFormedTenantId,
} from './last-active-tenant';

/**
 * Persist the tenant the user just activated.
 *
 * @param tenantId The tenant id that became active; ignored when malformed or
 *   when there is no authenticated session.
 */
export async function persistLastActiveTenant(tenantId: string): Promise<void> {
  if (!isWellFormedTenantId(tenantId)) {
    return;
  }
  const session = await getAuthSession();
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) {
    return;
  }
  const store = await cookies();
  store.set(LAST_ACTIVE_TENANT_COOKIE, tenantId, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: LAST_ACTIVE_TENANT_MAX_AGE_SECONDS,
  });
}
