/**
 * Server-side forwarders for the admin sign-up policy proxy (SGN-1.4, #5653).
 *
 * The Sign-up card on System settings cannot call apiome-rest directly (different origin; the
 * signed `admin_session` cookie lives on the UI domain), so its Next.js API route
 * (`src/app/api/admin/signup-policy`) forwards requests here. Like the sign-in provider proxy
 * (`admin-provider-config-proxy.ts`, whose transport this reuses), each forwarder presents the
 * signed session upstream — apiome-rest verifies it again — relays the upstream status and body
 * verbatim, and never throws.
 *
 * After a successful save, {@link proxyUpdateSignupPolicy} drops the in-process sign-up policy
 * cache: this proxy runs in the same Next.js process as sign-up enforcement, so the change applies
 * to the very next sign-up instead of after the cache lifetime.
 *
 * Server-only: import from API routes / server code, never from a client component.
 */
import { forwardToAdminRest, type AdminProviderProxyResult } from './admin-provider-config-proxy';
import type { AdminSignupPolicyUpdatePayload } from './admin-signup-policy';
import { invalidateSignupPolicyCache } from './signup-policy-resolver';

/**
 * Read the sign-up policy (forwards `GET /v1/admin/signup-policy`).
 *
 * @param adminSessionToken The verified signed admin-session token.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The upstream status and body (an `AdminSignupPolicyView` on 200).
 */
export async function proxyGetSignupPolicy(
  adminSessionToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AdminProviderProxyResult> {
  return forwardToAdminRest('/signup-policy', { method: 'GET' }, adminSessionToken, fetchImpl);
}

/**
 * Store, change or clear the sign-up policy (forwards `PUT /v1/admin/signup-policy`).
 *
 * @param adminSessionToken The verified signed admin-session token.
 * @param payload The new policy (`mode: null` clears the stored one), relayed verbatim.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The upstream status and body (the policy after the write on 200).
 */
export async function proxyUpdateSignupPolicy(
  adminSessionToken: string,
  payload: AdminSignupPolicyUpdatePayload,
  fetchImpl: typeof fetch = fetch,
): Promise<AdminProviderProxyResult> {
  const result = await forwardToAdminRest(
    '/signup-policy',
    { method: 'PUT', body: JSON.stringify(payload) },
    adminSessionToken,
    fetchImpl,
  );
  if (result.status >= 200 && result.status < 300) {
    invalidateSignupPolicyCache();
  }
  return result;
}

/**
 * Read the sign-up attempts an abuse guard refused (forwards
 * `GET /v1/admin/signup-policy/blocked-attempts`, SGN-1.5 #5654).
 *
 * @param adminSessionToken The verified signed admin-session token.
 * @param limit How many attempts to ask for (REST bounds it to 1–200).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The upstream status and body (a `BlockedSignupAttemptList` on 200).
 */
export async function proxyListBlockedSignupAttempts(
  adminSessionToken: string,
  limit: number,
  fetchImpl: typeof fetch = fetch,
): Promise<AdminProviderProxyResult> {
  const bounded = Math.min(200, Math.max(1, Math.trunc(Number.isFinite(limit) ? limit : 50)));
  return forwardToAdminRest(
    `/signup-policy/blocked-attempts?limit=${bounded}`,
    { method: 'GET' },
    adminSessionToken,
    fetchImpl,
  );
}
