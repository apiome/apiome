import { betterAuth } from 'better-auth';
import { createAuthMiddleware } from 'better-auth/api';
import { nextCookies } from 'better-auth/next-js';
import { genericOAuth } from 'better-auth/plugins/generic-oauth';
import {
  buildBetterAuthAdvancedOptions,
  buildBetterAuthSessionOptions,
  buildBetterAuthTrustedOrigins,
  resolveBetterAuthSecret,
} from './better-auth-session';
import {
  betterAuthEmailAndPassword,
  credentialRateLimitAfterHandler,
  credentialRateLimitBeforeHandler,
} from './better-auth-credentials';
import { oauthResolutionHandler } from './better-auth-account-resolution';
import {
  applyOauthRedirectOverride,
  buildGenericOAuthConfigs,
  runWithOauthRedirectOverride,
} from './better-auth-oauth-providers';
import { LINKABLE_PROVIDERS } from './account-resolution';

// The Better Auth server instance shares the same Postgres pool the rest of apiome-ui uses, so a
// migrated session/account read hits the same database as the REST API. `lib/db/db` is a CommonJS
// module (`module.exports = pool`, no ESM exports), so — like every other lib/db consumer — it is
// pulled in with `require`; an ESM default import fails typecheck ("not a module") for this file.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('../db/db');

/**
 * Better Auth server instance — the core install for the migration (OLO-10.2).
 *
 * This is the baseline the rest of Epic 10 builds on: it boots the Better Auth core (its four
 * models — `user`/`session`/`account`/`verification`) against the shared Postgres pool and nothing
 * more. There are deliberately **no social providers and no 2FA yet** — those arrive in later
 * tickets (providers in 10.7 #5002, 2FA in 10.10 #5005), as do the session/cookie parameters and the
 * `designer→spire` JWT plugin (10.3 #4998). See `docs/BETTER_AUTH_MIGRATION.md`.
 *
 * The instance is only exercised when `AUTH_ENGINE=better-auth`; with the default `next-auth` flag it
 * is never constructed (the catch-all route imports this module lazily — see the route handler).
 *
 * Config notes:
 * - `secret` reuses `NEXTAUTH_SECRET` so existing tooling and the suite's shared-secret assumption
 *   hold at cutover; a dedicated `BETTER_AUTH_SECRET` (or versioned `BETTER_AUTH_SECRETS`) can take
 *   over without a code change (design §1, {@link resolveBetterAuthSecret}).
 * - `baseURL` uses `BETTER_AUTH_URL` when set, otherwise the existing `NEXTAUTH_URL`.
 * - `basePath` stays at the default `/api/auth`, matching the route the app already serves, so no
 *   client/cookie path churn is needed at cutover.
 * - `session` / `advanced` / `trustedOrigins` implement the OLO-10.3 session strategy & cookie
 *   parity: a 30-day DB session with 24h refresh (matching NextAuth v4 defaults), a short signed
 *   cookie cache, and cross-subdomain cookie scoping + trusted origins on the same shared parent
 *   domain the legacy engine uses — so sessions persist across the app's subdomains exactly as today
 *   (`better-auth-session.ts`, `docs/BETTER_AUTH_MIGRATION.md` §1).
 * - `nextCookies()` must be the last plugin — it lets Better Auth set cookies from Next.js server
 *   actions (its standard App Router integration).
 */
export const auth = betterAuth({
  appName: 'apiome',
  database: connectionPool,
  secret: resolveBetterAuthSecret(),
  baseURL: process.env.BETTER_AUTH_URL ?? process.env.NEXTAUTH_URL,
  basePath: '/api/auth',
  trustedOrigins: buildBetterAuthTrustedOrigins(),
  session: buildBetterAuthSessionOptions(),
  advanced: buildBetterAuthAdvancedOptions(),
  // Keep apiome's existing `users` table as Better Auth's `user` model (design §2.1): map the model
  // name (plural table) and the columns that differ from Better Auth's camelCase defaults —
  // `emailVerified → verified` (already boolean, no timestamp conversion) and the snake_case
  // `created_at`/`updated_at`. The reused `users.id` (UUID) is the FK the `session`/`account` tables
  // created by V199 point at. Without this mapping the credential login (below) cannot read the user.
  user: {
    modelName: 'users',
    fields: {
      emailVerified: 'verified',
      createdAt: 'created_at',
      updatedAt: 'updated_at',
    },
  },
  // Credential (email/password) sign-in on the relocated `account` password (OLO-10.5): bcrypt
  // hash/verify so the migrated bcrypt hashes validate under Better Auth (which defaults to scrypt),
  // email verification required (mapped onto `users.verified`), self-service sign-up disabled (new
  // accounts still flow through apiome's signup/admin path, which dual-writes the credential account).
  // See `better-auth-credentials.ts` and docs/BETTER_AUTH_MIGRATION.md §2.3.
  emailAndPassword: betterAuthEmailAndPassword,
  // Account linking is reached only *after* the account-resolution engine has admitted the sign-in
  // in each provider's `getUserInfo` (10.7) — the engine rejects every unverified/forged identity
  // and routes brand-new users to onboarding before Better Auth's own handling runs. So on the admit
  // path Better Auth's email-based auto-link to an existing user is safe, and restricting it to the
  // OAuth vocabulary (`LINKABLE_PROVIDERS`: github|gitlab|azure|google) with a required verified
  // email keeps a stray provider from ever linking on its own.
  account: {
    accountLinking: {
      enabled: true,
      trustedProviders: [...LINKABLE_PROVIDERS],
    },
  },
  // The four live OAuth providers, re-expressed on Better Auth's generic OAuth2/OIDC plugin (10.7
  // #5002). Every provider is built from the shared registry (`enabledProviders`), so the enabled set
  // is identical to the NextAuth path and unsetting a provider's env removes its sign-in route. Each
  // provider's `getUserInfo` re-attaches verified-email normalization (OLO-2.5), the Google `hd` gate
  // (OLO-9.2), the azure nOAuth claims (OLO-1.4), and the account-resolution decision (OLO-10.6) —
  // see `better-auth-oauth-providers.ts`. `genericOAuth` mounts the `/oauth2/callback/:id` route the
  // 10.6 resolution adapter already recognises; it must come before `nextCookies()` (which stays
  // last so Better Auth can set cookies from Next.js server actions).
  plugins: [genericOAuth({ config: buildGenericOAuthConfigs() }), nextCookies()],
  // Credential brute-force limiting (OLO-10.5): the `before` handler refuses a locked
  // `/sign-in/email` attempt before any password work; the `after` handler records the outcome. Both
  // are path-gated and no-op for requests they do not own.
  //
  // OAuth account-resolution / nOAuth (OLO-10.6/10.7): the 10.6 `oauthResolutionHandler` reads a
  // `ctx.oauth` payload that would only exist *after* the code exchange, which a `before` hook runs
  // ahead of — so it stays a no-op here. 10.7 finalizes the placement by running the same engine
  // inside each provider's `getUserInfo` (`better-auth-oauth-providers.ts`), the one point in the
  // generic-OAuth callback that has the fetched profile + tokens *before* any user is created. The
  // hook is retained (inert) as defense-in-depth so the resolution gate remains composed on the
  // instance even if a future callback path surfaces `ctx.oauth`.
  hooks: {
    before: createAuthMiddleware(async (ctx) => {
      await credentialRateLimitBeforeHandler(ctx);
      await oauthResolutionHandler(ctx);
    }),
    after: createAuthMiddleware(async (ctx) => {
      await credentialRateLimitAfterHandler(ctx);
    }),
  },
});

/**
 * Better Auth request handler for the `/api/auth/[...all]` catch-all.
 *
 * `auth.handler` dispatches on the request method and path internally, so a single function serves
 * every Better Auth endpoint (GET and POST alike). The parallel-run route delegates to this when the
 * `AUTH_ENGINE` flag selects Better Auth.
 *
 * The call is wrapped in a per-request redirect-override scope (OLO-10.7): an OAuth provider's
 * `getUserInfo` runs the account-resolution engine and, on any non-admit outcome, publishes the
 * engine's exact redirect path; here we rewrite the Better Auth redirect's `Location` to that path so
 * a rejection lands on the byte-identical `/login?error=<code>` (and onboarding/link) contract
 * (`better-auth-oauth-providers.ts`). For an admitted sign-in no override is set and the response is
 * returned untouched.
 *
 * @param request The incoming request from the Next.js App Router route.
 * @returns The Better Auth response, with an OAuth redirect retargeted when the engine rejected.
 */
export function betterAuthHandler(request: Request): Promise<Response> {
  return runWithOauthRedirectOverride(async () => {
    const response = await auth.handler(request);
    return applyOauthRedirectOverride(response);
  });
}
