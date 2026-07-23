/**
 * Better Auth credential (email/password) wiring for the migration (OLO-10.5, #5000).
 *
 * Two things must be preserved when password sign-in moves from NextAuth onto Better Auth:
 *
 *  1. **bcrypt verification.** apiome's stored password hashes are bcrypt (cost 10, `$2a$`/`$2b$`),
 *     relocated onto `account.password` (providerId=`credential`) by V200. Better Auth hashes with
 *     **scrypt** by default and would reject every existing hash. {@link bcryptPasswordConfig}
 *     overrides Better Auth's `emailAndPassword.password` with bcrypt `hash`/`verify` so the relocated
 *     hashes keep verifying unchanged, and any password Better Auth writes stays bcrypt — so a
 *     rollback to the legacy `users.password` column (still bcrypt) loses nothing.
 *
 *  2. **Per-account + per-IP brute-force limiting.** The NextAuth path enforces the in-process
 *     sliding-window limiter (`login-rate-limit.ts`): a per-account lock (`cred:<email>`, 5 attempts)
 *     and a looser per-IP lock (`cred-ip:<ip>`, 20 attempts). {@link credentialRateLimitBefore} /
 *     {@link credentialRateLimitAfter} re-apply that exact limiter around Better Auth's
 *     `/sign-in/email` endpoint so the throttle behaves identically on either engine.
 *
 * See docs/BETTER_AUTH_MIGRATION.md §2.3 / §4 and apiome-ui/lib/auth/credentials.ts (the NextAuth
 * counterpart, which stays the active path until cutover).
 */

import { createAuthMiddleware, APIError } from 'better-auth/api';

import { resolveClientIp, type HeaderLookup } from './client-ip';
import {
  AUTH_RATE_LIMITED_CODE,
  CREDENTIALS_IP_MAX_ATTEMPTS,
  checkLoginRateLimit,
  credentialsIpRateLimitKey,
  credentialsRateLimitKey,
  recordLoginFailure,
  recordLoginSuccess,
} from './login-rate-limit';

// bcrypt is a native CJS module (same import style as the rest of the codebase).
// eslint-disable-next-line @typescript-eslint/no-require-imports
const bcrypt = require('bcrypt');

/**
 * bcrypt cost factor for newly-hashed passwords. Matches every other password write in apiome
 * (`admin-helper.ts`, `helper.ts` — cost 10), so hashes are interchangeable across engines.
 */
export const BCRYPT_COST = 10;

/** Better Auth's endpoint path for email/password sign-in — the only path the limiter guards. */
export const SIGN_IN_EMAIL_PATH = '/sign-in/email';

/**
 * bcrypt hashing/verification for Better Auth's `emailAndPassword.password` option.
 *
 * `verify` runs `bcrypt.compare`, which transparently reads the cost and salt from the stored hash,
 * so it validates the relocated `$2a$`/`$2b$` hashes exactly as the NextAuth path did. `hash` uses
 * {@link BCRYPT_COST} so any Better Auth-written password stays bcrypt and rollback-compatible.
 */
export const bcryptPasswordConfig = {
  hash: (password: string): Promise<string> => bcrypt.hash(password, BCRYPT_COST),
  verify: ({ hash, password }: { hash: string; password: string }): Promise<boolean> =>
    bcrypt.compare(password, hash),
};

/**
 * The subset of the Better Auth middleware context this module reads. Declared structurally (rather
 * than pulling Better Auth's full internal context type) so the hooks stay decoupled from Better
 * Auth's internals — we only ever touch the request path, the sign-in body, the headers, and whether
 * a session was established.
 */
interface CredentialMiddlewareContext {
  path?: string;
  body?: { email?: unknown };
  headers?: HeaderLookup | null;
  request?: { headers?: HeaderLookup | null };
  context?: { newSession?: unknown };
}

/**
 * Read the submitted email + resolved client IP from a Better Auth middleware context, and derive the
 * per-account and per-IP rate-limit keys used by both engines.
 *
 * @param ctx The Better Auth middleware context (`createAuthMiddleware` handler argument).
 * @returns The account key (`cred:<email>` or null) and IP key (`cred-ip:<ip>` or null).
 */
function rateLimitKeysFromContext(ctx: CredentialMiddlewareContext): {
  accountKey: string | null;
  ipKey: string | null;
} {
  const email = typeof ctx.body?.email === 'string' ? ctx.body.email : undefined;
  const headers = ctx.headers ?? ctx.request?.headers ?? null;
  const ip = resolveClientIp(headers);
  return {
    accountKey: credentialsRateLimitKey(email),
    ipKey: credentialsIpRateLimitKey(ip),
  };
}

/**
 * `hooks.before` middleware: refuse a locked credential sign-in before any password work.
 *
 * Runs only for `POST /sign-in/email`. Checks the per-IP lock first (the looser, host-wide cap) then
 * the per-account lock; either being engaged throws a structured `TOO_MANY_REQUESTS` carrying
 * {@link AUTH_RATE_LIMITED_CODE} — the same code the REST surface and NextAuth path return, so clients
 * handle the throttle identically. Non-sign-in requests pass through untouched.
 */
export const credentialRateLimitBefore = createAuthMiddleware(async (ctx) => {
  const context = ctx as unknown as CredentialMiddlewareContext;
  if (context.path !== SIGN_IN_EMAIL_PATH) {
    return;
  }
  const now = Date.now();
  const { accountKey, ipKey } = rateLimitKeysFromContext(context);

  if (ipKey && checkLoginRateLimit(ipKey, now, CREDENTIALS_IP_MAX_ATTEMPTS).blocked) {
    throw new APIError('TOO_MANY_REQUESTS', {
      message: 'Too many failed sign-in attempts from this client. Try again later.',
      code: AUTH_RATE_LIMITED_CODE,
    });
  }
  if (accountKey && checkLoginRateLimit(accountKey, now).blocked) {
    throw new APIError('TOO_MANY_REQUESTS', {
      message: 'Too many failed sign-in attempts for this account. Try again later.',
      code: AUTH_RATE_LIMITED_CODE,
    });
  }
});

/**
 * `hooks.after` middleware: record the credential sign-in outcome against both limiters.
 *
 * Runs only for `POST /sign-in/email`, after the endpoint has executed. Better Auth converts a failed
 * sign-in (bad password, unknown/unverified account) into a returned `APIError` rather than an
 * unhandled throw, so this hook fires on both outcomes: a successful sign-in (`ctx.context.newSession`
 * is set) clears both keys; any other outcome records a failure against the per-account lock and the
 * looser per-IP lock — matching the NextAuth path's accounting exactly.
 */
export const credentialRateLimitAfter = createAuthMiddleware(async (ctx) => {
  const context = ctx as unknown as CredentialMiddlewareContext;
  if (context.path !== SIGN_IN_EMAIL_PATH) {
    return;
  }
  const { accountKey, ipKey } = rateLimitKeysFromContext(context);
  const succeeded = Boolean(context.context?.newSession);

  if (succeeded) {
    if (accountKey) recordLoginSuccess(accountKey);
    if (ipKey) recordLoginSuccess(ipKey);
    return;
  }

  if (accountKey) recordLoginFailure(accountKey);
  if (ipKey) recordLoginFailure(ipKey, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS);
});

/**
 * The Better Auth `emailAndPassword` block for the migrated credential login (OLO-10.5).
 *
 * Enables email/password sign-in against the relocated credential accounts, with bcrypt
 * hashing/verification and email-verification required (mapping onto apiome's `users.verified` gate
 * via the instance's `user` field mapping). Self-service sign-up stays disabled: new accounts are
 * still provisioned through apiome's existing signup/admin flow (which dual-writes the credential
 * account), so Better Auth never inserts into the `NOT NULL`-constrained `users` table directly.
 */
export const betterAuthEmailAndPassword = {
  enabled: true,
  disableSignUp: true,
  requireEmailVerification: true,
  password: bcryptPasswordConfig,
} as const;
