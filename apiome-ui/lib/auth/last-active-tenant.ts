/**
 * Durable last-active-tenant persistence (OLO-6.1, #4218).
 *
 * The OLO-3.3 post-login routing restores the "last-active" tenant, but its
 * only candidate used to be `token.current_tenant_id` — which lives inside the
 * session JWT and vanishes with it on logout/expiry. This module keeps the
 * last-active tenant in its own long-lived cookie so a *fresh* login can hand
 * it to `resolveActiveTenantForLogin` as the candidate.
 *
 * The cookie is a hint, never an authority: the login path validates it
 * against the user's live memberships (`pickActiveTenantId`), so a stale or
 * tampered value degrades to the default tenant instead of granting anything.
 *
 * Server-only module (uses `next/headers`); the client-callable write action
 * lives in `last-active-tenant-actions.ts`.
 */

import { cookies } from 'next/headers';
import { getSharedCookieDomain } from './cookie-options';

/** Cookie holding the last tenant the user activated. */
export const LAST_ACTIVE_TENANT_COOKIE = 'apiome.last-active-tenant';

/** Cookie lifetime: 180 days, refreshed on every switch. */
export const LAST_ACTIVE_TENANT_MAX_AGE_SECONDS = 60 * 60 * 24 * 180;

/** The attributes every writer of the last-active-tenant cookie sets. */
export interface LastActiveTenantCookieOptions {
  httpOnly: true;
  sameSite: 'lax';
  secure: boolean;
  path: '/';
  maxAge: number;
  /** The shared parent domain, when one applies; absent means host-only (development). */
  domain?: string;
}

/**
 * The cookie attributes for the last-active tenant — **the only place they are stated** (BAA-2.2,
 * apiome #6565).
 *
 * The tenant hint has to ride the same scope as the session cookie it qualifies. Better Auth scopes
 * the session cookie to {@link getSharedCookieDomain} (`BETTER_AUTH_COOKIE_DOMAIN`, inferred from
 * the app URLs otherwise), so a sign-in on the main app is a sign-in on the studio; a host-only
 * tenant cookie beside it meant the two origins read the **same session** but derived **different
 * active tenants**, and the service bearer each minted named a different `current_tenant_id`.
 * Scoping it here, from the same resolver, keeps "the workspace you picked" a fact about the
 * sign-in rather than about the origin you picked it on. Outside production the resolver answers
 * `undefined` and the cookie stays host-only, exactly like the session cookie.
 *
 * Every writer calls this; `serverLogout` (`logout-actions.ts`) expires both the host-only and the
 * domain-scoped form, because a host-only delete cannot remove a domain-scoped cookie.
 *
 * @returns The options to pass to `cookies().set(LAST_ACTIVE_TENANT_COOKIE, tenantId, options)`.
 */
export function lastActiveTenantCookieOptions(): LastActiveTenantCookieOptions {
  const domain = getSharedCookieDomain();
  return {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: LAST_ACTIVE_TENANT_MAX_AGE_SECONDS,
    ...(domain ? { domain } : {}),
  };
}

/** Shape guard for tenant ids (UUID string) before trusting a cookie/input. */
const TENANT_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a value looks like a tenant id (UUID). Used both before writing the
 * cookie and before offering its value as a login candidate.
 *
 * @param value The candidate tenant id.
 * @returns True when the value is a well-formed UUID string.
 */
export function isWellFormedTenantId(value: unknown): value is string {
  return typeof value === 'string' && TENANT_ID_PATTERN.test(value);
}

/**
 * Read the last-active tenant id from the request's cookies.
 *
 * @returns The cookie's tenant id, or null when absent or malformed.
 */
export async function readLastActiveTenantId(): Promise<string | null> {
  const store = await cookies();
  const value = store.get(LAST_ACTIVE_TENANT_COOKIE)?.value;
  return isWellFormedTenantId(value) ? value : null;
}
