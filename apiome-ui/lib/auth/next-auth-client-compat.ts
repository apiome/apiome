/**
 * NextAuth browser transport for the engine-aware session compat layer (OLO-10.12, #5007).
 *
 * The app must keep working under the default `next-auth` engine while importing **zero**
 * `next-auth/react` — so this module re-implements the handful of client operations the UI needs by
 * calling NextAuth v4's own HTTP endpoints directly (the same endpoints `next-auth/react` calls under
 * the hood, mounted by the parallel-run `[...nextauth]` route):
 *
 * - session read  → `GET  /api/auth/session`      (returns the app-shaped session or `{}`)
 * - CSRF token     → `GET  /api/auth/csrf`
 * - session update → `POST /api/auth/session`      (triggers the `jwt` callback, `trigger: 'update'`)
 * - credentials    → `POST /api/auth/callback/credentials`
 * - OAuth sign-in  → `POST /api/auth/signin/:provider`
 * - sign-out       → `POST /api/auth/signout`
 *
 * Each mutating call carries the CSRF token and `json: 'true'` so NextAuth returns `{ url }` instead of
 * a 302; the caller navigates to that URL — byte-for-byte what `next-auth/react` did. Used only when
 * `NEXT_PUBLIC_AUTH_ENGINE` is not `better-auth`; the Better Auth counterpart is
 * `better-auth-client-compat.ts`.
 */

import type { AppSession } from './better-auth-session-shape';

/** NextAuth's base path, matching `basePath: '/api/auth'` on the Better Auth side. */
const AUTH_BASE = '/api/auth';

/** Fetch a fresh CSRF token; every NextAuth mutating endpoint requires it. */
async function getCsrfToken(): Promise<string> {
  const res = await fetch(`${AUTH_BASE}/csrf`, { credentials: 'include' });
  const body = (await res.json().catch(() => ({}))) as { csrfToken?: string };
  return body.csrfToken ?? '';
}

/** POST a form-encoded body to a NextAuth endpoint with `json: true` and return the parsed JSON. */
async function postForm(path: string, fields: Record<string, string>): Promise<{ url?: string }> {
  const csrfToken = await getCsrfToken();
  const res = await fetch(`${AUTH_BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ ...fields, csrfToken, json: 'true' }),
  });
  return (await res.json().catch(() => ({}))) as { url?: string };
}

/**
 * Read the current NextAuth session.
 *
 * `GET /api/auth/session` returns the app-shaped session (the `session` callback injects
 * `user_id`/`current_tenant_id`, `[...nextauth]/route.ts`) or `{}` when signed out.
 *
 * @returns The session, or `null` when there is none.
 */
export async function getNextAuthSession(): Promise<AppSession | null> {
  const res = await fetch(`${AUTH_BASE}/session`, { credentials: 'include' });
  if (!res.ok) {
    return null;
  }
  const body = (await res.json().catch(() => null)) as AppSession | Record<string, never> | null;
  if (!body || !('user' in body) || !body.user) {
    return null;
  }
  return body as AppSession;
}

/**
 * Push a session update through NextAuth so the JWT is refreshed (the `jwt` callback runs with
 * `trigger: 'update'` and re-validates the payload, e.g. a tenant switch, `[...nextauth]/route.ts`).
 *
 * @param data The partial session to merge (e.g. `{ current_tenant_id }` or `{ name }`).
 */
export async function updateNextAuthSession(data: Record<string, unknown>): Promise<void> {
  const csrfToken = await getCsrfToken();
  await fetch(`${AUTH_BASE}/session`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ csrfToken, data: JSON.stringify(data) }),
  });
}

/**
 * Sign in via NextAuth and navigate to the resolved URL, matching `next-auth/react`'s
 * `signIn(provider, { callbackUrl, redirect: true })`.
 *
 * @param provider `'credentials'` or an OAuth provider id.
 * @param options `callbackUrl` (where to land on success) and, for credentials, the `payload` JSON
 *   blob (`{email,password}` or `{oneTimeCode}`) the `authorize` callback parses.
 */
export async function signInNextAuth(
  provider: string,
  options: { callbackUrl?: string; payload?: string } = {}
): Promise<void> {
  const callbackUrl = options.callbackUrl ?? window.location.href;
  const result =
    provider === 'credentials'
      ? await postForm('/callback/credentials', { callbackUrl, payload: options.payload ?? '{}' })
      : await postForm(`/signin/${provider}`, { callbackUrl });
  if (result.url) {
    window.location.href = result.url;
  }
}

/**
 * Sign out via NextAuth and navigate to `callbackUrl`.
 *
 * @param callbackUrl Where to land after sign-out.
 */
export async function signOutNextAuth(callbackUrl: string): Promise<void> {
  const result = await postForm('/signout', { callbackUrl });
  window.location.href = result.url ?? callbackUrl;
}
