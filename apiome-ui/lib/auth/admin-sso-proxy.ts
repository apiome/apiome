/**
 * Server-side forwarder for the admin console's SSO providers section (EID-1.1, #5011).
 *
 * The settings screen cannot call apiome-rest directly (different origin; the signed `admin_session`
 * cookie lives on the UI domain), so `src/app/api/admin/sso/providers/[[...path]]` forwards here,
 * after verifying the session. Like the sign-in provider proxy (`admin-provider-config-proxy.ts`)
 * it presents the same signed token upstream — apiome-rest verifies it again, so the proxy adds no
 * authority of its own — relays status and body verbatim, and never throws.
 *
 * Unlike a per-route proxy it serves several upstream paths, so it forwards **only** the path
 * shapes the REST surface defines ({@link ssoAdminUpstreamPath}); anything else is refused locally
 * with `404` and never reaches REST — the route cannot be turned into an open proxy into the admin
 * API.
 *
 * A successful write clears the in-process routable-provider cache, so the next sign-in sees an
 * enabled provider or a newly verified domain at once.
 *
 * Server-only.
 */

import { forwardToAdminRest, type AdminProviderProxyResult } from './admin-provider-config-proxy';
import { invalidateSsoProviderCache } from './sso-provider-resolver';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DOMAIN = /^[a-z0-9.-]{1,253}$/i;

/** The method and path shapes the REST surface (`/v1/admin/sso/providers`) defines. */
const ALLOWED: ReadonlyArray<{ methods: readonly string[]; shape: (s: string[]) => boolean }> = [
  { methods: ['GET', 'POST'], shape: (s) => s.length === 0 },
  { methods: ['GET', 'PATCH', 'DELETE'], shape: (s) => s.length === 1 && UUID.test(s[0]) },
  { methods: ['POST'], shape: (s) => s.length === 2 && UUID.test(s[0]) && s[1] === 'domains' },
  {
    methods: ['DELETE'],
    shape: (s) => s.length === 3 && UUID.test(s[0]) && s[1] === 'domains' && DOMAIN.test(s[2]),
  },
  {
    methods: ['POST'],
    shape: (s) => s.length === 4 && UUID.test(s[0]) && s[1] === 'domains' && DOMAIN.test(s[2]) && s[3] === 'verify',
  },
];

/**
 * The upstream path for a proxied request, or null when the method/path is not one the REST
 * surface defines.
 *
 * @param method The HTTP method.
 * @param segments The `[[...path]]` segments after `/api/admin/sso/providers`.
 * @returns `/sso/providers…` under `/v1/admin`, or null.
 */
export function ssoAdminUpstreamPath(method: string, segments: readonly string[]): string | null {
  const verb = method.toUpperCase();
  const parts = [...segments];
  const allowed = ALLOWED.some((rule) => rule.methods.includes(verb) && rule.shape(parts));
  if (!allowed) return null;
  return `/sso/providers${parts.map((p) => `/${encodeURIComponent(p.toLowerCase())}`).join('')}`;
}

/**
 * Forward one admin SSO request to apiome-rest.
 *
 * @param adminSessionToken The verified signed admin-session token.
 * @param method The HTTP method.
 * @param segments The path segments after `/api/admin/sso/providers`.
 * @param body The JSON body for POST/PATCH, relayed verbatim (may carry a write-only secret —
 *   never logged).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The upstream status and body; `404` locally for a path REST does not define.
 */
export async function proxySsoAdmin(
  adminSessionToken: string,
  method: string,
  segments: readonly string[],
  body?: unknown,
  fetchImpl: typeof fetch = fetch
): Promise<AdminProviderProxyResult> {
  const upstream = ssoAdminUpstreamPath(method, segments);
  if (!upstream) {
    return { status: 404, body: { error: 'not_found', message: 'No such SSO admin route.' } };
  }
  const verb = method.toUpperCase();
  const result = await forwardToAdminRest(
    upstream,
    { method: verb, body: body === undefined ? undefined : JSON.stringify(body) },
    adminSessionToken,
    fetchImpl
  );
  if (verb !== 'GET' && result.status >= 200 && result.status < 300) {
    invalidateSsoProviderCache();
  }
  return result;
}
