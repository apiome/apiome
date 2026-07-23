import { createAuthClient } from 'better-auth/react';

/**
 * Better Auth browser client (OLO-10.2).
 *
 * The React client the UI will call as `authClient.signIn` / `authClient.signOut` /
 * `authClient.useSession` once the `signIn`/`signOut`/`useSession` swap lands (10.12 #5007). This
 * ticket only stands the client up; no component consumes it yet.
 *
 * `basePath` stays at the default `/api/auth`, which the app already serves same-origin, so the
 * client needs no explicit `baseURL` in the browser — it resolves against the current origin.
 */
export const authClient = createAuthClient({
  basePath: '/api/auth',
});
