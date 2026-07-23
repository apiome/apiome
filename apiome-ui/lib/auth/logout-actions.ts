'use server';

/**
 * Deterministic server-side logout (companion to NextAuth's client `signOut`).
 *
 * NextAuth's default client `signOut` is the only thing that clears the session
 * on logout, and it has proven unreliable here: the session JWT cookie can
 * survive the sign-out round-trip, and because `/login` redirects any *live*
 * session back into the app (post-login routing, OLO-3.3), a surviving cookie
 * leaves the user looking still-logged-in on `/ade`. It also never clears the
 * durable `apiome.last-active-tenant` cookie, so the next login silently
 * restores the old tenant.
 *
 * This action force-expires those cookies server-side so logout does not depend
 * on NextAuth's cookie handling. It mirrors the shared-cookie awareness of
 * `clearSessionCookie` (stale-session-cookie.ts): a plain host-only expiry does
 * not remove a cookie scoped to `NEXTAUTH_COOKIE_DOMAIN`, so both variants are
 * emitted in production.
 */

import { cookies } from 'next/headers';
import { getSharedCookieDomain } from './cookie-options';
import { LAST_ACTIVE_TENANT_COOKIE } from './last-active-tenant';

/**
 * Every NextAuth session-token cookie name we might have written across dev
 * (unprefixed) and production (`__Secure-`/`__Host-` prefixed) configs. Mirrors
 * the list in stale-session-cookie.ts so both clear paths agree.
 */
const SESSION_COOKIE_NAMES = [
  'next-auth.session-token',
  '__Secure-next-auth.session-token',
  '__Host-next-auth.session-token',
] as const;

/**
 * Clear the NextAuth session cookie(s) and the durable last-active-tenant
 * cookie so a logout deterministically ends the session.
 *
 * Safe to call redundantly (e.g. alongside NextAuth's own `signOut`): expiring
 * an absent cookie is a no-op.
 */
export async function serverLogout(): Promise<void> {
  const store = await cookies();
  const domain = getSharedCookieDomain();

  // Durable tenant hint: host-scoped only, so a single host-only delete suffices.
  store.delete(LAST_ACTIVE_TENANT_COOKIE);

  for (const name of SESSION_COOKIE_NAMES) {
    // `__Secure-`/`__Host-` cookies only ever exist over https, so they must be
    // expired with Secure to match; the unprefixed dev cookie follows NODE_ENV.
    const secure = name.startsWith('__') || process.env.NODE_ENV === 'production';
    const base = {
      path: '/',
      httpOnly: true,
      sameSite: 'lax' as const,
      secure,
      maxAge: 0,
    };

    // Host-only expiry — removes the dev cookie and any host-scoped session.
    store.set(name, '', base);

    // Domain-scoped expiry for the shared cross-subdomain cookie. `__Host-`
    // cookies are host-locked and cannot carry a Domain, so they are excluded.
    if (domain && !name.startsWith('__Host-')) {
      store.set(name, '', { ...base, domain });
    }
  }
}
