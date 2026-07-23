import { betterAuth } from 'better-auth';
import { nextCookies } from 'better-auth/next-js';

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
 *   hold at cutover; a dedicated `BETTER_AUTH_SECRET` can take over later (design §1).
 * - `baseURL` uses `BETTER_AUTH_URL` when set, otherwise the existing `NEXTAUTH_URL`.
 * - `basePath` stays at the default `/api/auth`, matching the route the app already serves, so no
 *   client/cookie path churn is needed at cutover.
 * - `nextCookies()` must be the last plugin — it lets Better Auth set cookies from Next.js server
 *   actions (its standard App Router integration).
 */
export const auth = betterAuth({
  appName: 'apiome',
  database: connectionPool,
  secret: process.env.NEXTAUTH_SECRET,
  baseURL: process.env.BETTER_AUTH_URL ?? process.env.NEXTAUTH_URL,
  basePath: '/api/auth',
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
