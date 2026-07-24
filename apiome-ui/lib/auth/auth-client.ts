import { createAuthClient } from 'better-auth/react';
import {
  twoFactorClient,
  customSessionClient,
  genericOAuthClient,
} from 'better-auth/client/plugins';
// Type-only import: erased at compile time, so the server instance (and its Postgres pool) is never
// bundled into the browser client. It exists purely so `customSessionClient` can infer the extra
// session fields (`user_id`/`current_tenant_id`) the server `customSession` plugin injects (OLO-10.12).
import type { BetterAuthInstance } from './auth';

/**
 * Better Auth browser client (OLO-10.2, extended for 2FA in OLO-10.10).
 *
 * The React client the UI will call as `authClient.signIn` / `authClient.signOut` /
 * `authClient.useSession` once the `signIn`/`signOut`/`useSession` swap lands (10.12 #5007). This
 * ticket only stands the client up; no component consumes it yet.
 *
 * `basePath` stays at the default `/api/auth`, which the app already serves same-origin, so the
 * client needs no explicit `baseURL` in the browser — it resolves against the current origin.
 *
 * `twoFactorClient()` is the browser counterpart of the server `twoFactor` plugin (OLO-10.10 #5005):
 * it exposes `authClient.twoFactor.*` (enable / disable / verifyTotp / …) and the second-factor
 * redirect hook the login step will use. Registered here as foundation only — the enrollment and
 * login-step UX are OLO-9.13 (#5014) / OLO-9.14 (#5006). The client plugin must be present so the
 * client's type inference and the `two-factor` path routing match the server instance.
 *
 * `customSessionClient()` mirrors the server `customSession` plugin so `authClient.useSession()` typing
 * carries the injected `user_id`/`current_tenant_id` (OLO-10.12).
 *
 * `genericOAuthClient()` is the browser counterpart of the server `genericOAuth` plugin (OLO-10.7): it
 * exposes `authClient.signIn.oauth2({ providerId, callbackURL })`, the client entry point the OAuth
 * sign-in / account-link buttons call after the swap (OLO-10.12).
 */
export const authClient = createAuthClient({
  basePath: '/api/auth',
  plugins: [
    twoFactorClient(),
    customSessionClient<BetterAuthInstance>(),
    genericOAuthClient(),
  ],
});
