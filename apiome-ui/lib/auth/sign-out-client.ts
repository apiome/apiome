'use client';

/**
 * Single logout entry point for every "Sign out" control.
 *
 * Runs the deterministic server-side cookie clear (serverLogout) *before*
 * handing off to the engine-aware client `signOut`, so the session cookie is
 * gone regardless of the active engine's own cookie handling, and the durable
 * last-active-tenant cookie is cleared too. The engine `signOut`
 * (`session-client.tsx`, OLO-10.12) then clears the Better Auth / NextAuth
 * session and performs the redirect.
 */

import { signOut } from './session-client';
import { serverLogout } from './logout-actions';

/**
 * Sign the user out everywhere and redirect to `callbackUrl`.
 *
 * @param callbackUrl Where to land after sign-out (e.g. `/login`, or the main
 *   app's `/login` when signing out from the studio shell).
 */
export async function signOutEverywhere(callbackUrl: string): Promise<void> {
  // Best-effort: a server-clear failure must not block the client sign-out and
  // redirect, which still expires the session the normal way.
  try {
    await serverLogout();
  } catch (error) {
    console.error('[auth] server-side logout cookie clear failed:', error);
  }
  await signOut(callbackUrl);
}
