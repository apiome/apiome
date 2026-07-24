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
import { validateTenantSwitch } from './post-login-routing';

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
  await writeLastActiveTenantCookie(tenantId);
}

/** Write the durable last-active-tenant cookie for an already-validated tenant id. */
async function writeLastActiveTenantCookie(tenantId: string): Promise<void> {
  const store = await cookies();
  store.set(LAST_ACTIVE_TENANT_COOKIE, tenantId, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: LAST_ACTIVE_TENANT_MAX_AGE_SECONDS,
  });
}

/**
 * Switch the active tenant (OLO-10.12, #5007) — the engine-agnostic replacement for the NextAuth
 * `useSession().update({ current_tenant_id })` persistence.
 *
 * Under Better Auth a session carries no tenant claim: the active tenant is **derived** at read time
 * from the durable last-active-tenant cookie, re-validated against live memberships
 * (`better-auth-session-shape.ts`). So writing that cookie *is* the switch. This action re-validates
 * the requested tenant against the caller's live memberships (`validateTenantSwitch`, the OLO-7.3
 * threat-model gate) **before** writing, so a tampered request can never point tenant-scoped queries at
 * a tenant the user does not belong to — the same guarantee the NextAuth `jwt` callback enforced.
 *
 * Fails closed: an unauthenticated caller, a malformed id, or a non-member request writes nothing and
 * returns `null`.
 *
 * @param tenantId The tenant the user asked to activate.
 * @returns The validated tenant id that was persisted, or `null` when the switch was refused.
 */
export async function setActiveTenant(tenantId: string): Promise<string | null> {
  if (!isWellFormedTenantId(tenantId)) {
    return null;
  }
  const session = await getAuthSession();
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) {
    return null;
  }
  const validated = await validateTenantSwitch(userId, tenantId);
  if (!validated) {
    return null;
  }
  await writeLastActiveTenantCookie(validated);
  return validated;
}
