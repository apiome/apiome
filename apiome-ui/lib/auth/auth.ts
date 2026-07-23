import { betterAuth } from 'better-auth';
import { nextCookies } from 'better-auth/next-js';
import {
  buildBetterAuthAdvancedOptions,
  buildBetterAuthSessionOptions,
  buildBetterAuthTrustedOrigins,
  resolveBetterAuthSecret,
} from './better-auth-session';
import {
  betterAuthEmailAndPassword,
  credentialRateLimitAfter,
  credentialRateLimitBefore,
} from './better-auth-credentials';

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
  // Preserve the per-account + per-IP brute-force limiting around credential sign-in exactly as the
  // NextAuth path does (`login-rate-limit.ts`): the `before` hook refuses a locked attempt before any
  // password work; the `after` hook records the outcome. Both no-op for non-`/sign-in/email` requests.
  hooks: {
    before: credentialRateLimitBefore,
    after: credentialRateLimitAfter,
  },
  plugins: [nextCookies()],
});

/**
 * Better Auth request handler for the `/api/auth/[...all]` catch-all.
 *
 * `auth.handler` dispatches on the request method and path internally, so a single function serves
 * every Better Auth endpoint (GET and POST alike). The parallel-run route delegates to this when the
 * `AUTH_ENGINE` flag selects Better Auth.
 *
 * @param request The incoming request from the Next.js App Router route.
 * @returns The Better Auth response.
 */
export function betterAuthHandler(request: Request): Promise<Response> {
  return auth.handler(request);
}
