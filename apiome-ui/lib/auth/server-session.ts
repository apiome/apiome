/**
 * Engine-aware server-side session reader (OLO-10.12, #5007).
 *
 * The whole server — ~106 API route handlers plus the server components/actions that guard protected
 * routes — reads the current session through this one helper. It returns the NextAuth-shaped app
 * contract (`session.user.user_id` / `current_tenant_id`) on **either** auth engine, so flipping
 * `AUTH_ENGINE` (see `auth-engine.ts`) changes nothing for callers:
 *
 * - **better-auth:** read the Better Auth database session (`auth.api.getSession`) and map it onto the
 *   app contract via `toAppSessionUser` (`user_id` = `user.id`, `current_tenant_id` derived from the
 *   validated last-active cookie). The mapping is applied here rather than relying on the server
 *   `customSession` plugin so a direct `auth.api.getSession()` call is shaped identically to the
 *   browser's `/get-session`.
 * - **next-auth:** the unchanged `getServerSession(authOptions)` path — its `session`/`jwt` callbacks
 *   already inject `user_id`/`current_tenant_id` (`[...nextauth]/route.ts`). The `next-auth` package is
 *   removed at cutover (OLO-10.14); until then a server-side import of it is expected and allowed.
 *
 * Each engine's dependencies are imported **lazily on its own branch** so the default `next-auth` path
 * never loads Better Auth's ESM-only modules (and vice-versa) — mirroring the parallel-run dispatch in
 * `[...nextauth]/route.ts`.
 *
 * This is a plain server module (no `'use server'`): every caller is server-side (route handlers,
 * server components, other server modules), so exporting a normal async function — rather than a
 * server action — keeps API routes off server-action semantics while its existing callers are
 * unchanged.
 */

import type { AppSession } from './better-auth-session-shape';
import { isBetterAuthEngine } from './auth-engine';

/**
 * The session shape returned to callers — the app contract carried on both engines. Every consumer
 * reads `session.user.user_id` / `current_tenant_id` (and occasionally `email`/`name`).
 */
export type AuthSession = AppSession;

/**
 * Read the current Better Auth session and map it onto the app contract.
 *
 * @returns The app-shaped session, or `null` when there is no active Better Auth session.
 */
async function getBetterAuthSession(): Promise<AuthSession | null> {
  const { headers } = await import('next/headers');
  const { auth } = await import('./auth');
  const { toAppSessionUser } = await import('./better-auth-session-shape');

  const result = await auth.api.getSession({ headers: await headers() });
  if (!result?.user) {
    return null;
  }
  return {
    user: await toAppSessionUser(result.user),
    expires: new Date(result.session.expiresAt).toISOString(),
  };
}

/**
 * Returns the current server session in the app-contract shape, or `null` when called outside an
 * authenticated request context (e.g. in unit tests with no mock).
 *
 * Engine-aware: reads Better Auth when `AUTH_ENGINE=better-auth`, otherwise the legacy NextAuth
 * session. The return shape is identical on both, so callers never branch on the engine.
 *
 * @returns The current session, or `null` when unauthenticated.
 */
export async function getAuthSession(): Promise<AuthSession | null> {
  if (isBetterAuthEngine()) {
    return getBetterAuthSession();
  }
  const { getServerSession } = await import('next-auth');
  const { authOptions } = await import('@/app/api/auth/[...nextauth]/route');
  return (await getServerSession(authOptions)) as AuthSession | null;
}
