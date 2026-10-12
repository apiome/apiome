/**
 * Fresh re-authentication for two-factor changes on accounts without a password (TFA-1.1, #5655).
 *
 * Turning two-factor on or off and making new backup codes are gated on the account's password.
 * An account that signs in only through a provider has none, so `auth.ts` sets the plugin's
 * `allowPasswordless` — which, on its own, would let any live session of such an account change
 * its second factor: a session left open on a shared machine could switch it off.
 *
 * This `hooks.before` handler puts the missing proof back. For those three endpoints, when the
 * session's user has **no** credential password, the session itself must be recent
 * ({@link isSessionFresh}): the reader has just signed in with their provider. A stale session is
 * refused with `403` and the stable code `REAUTH_REQUIRED`, and the Profile page offers
 * "Sign in again with <provider>".
 *
 * An account with a password is not touched here — the plugin still demands the password for it
 * (`shouldRequirePassword`), which is the stronger proof.
 */

import { APIError, getAuthoritativeSessionFromCtx } from 'better-auth/api';
import { REAUTH_REQUIRED_CODE, REAUTH_WINDOW_MINUTES, isSessionFresh } from './two-factor-policy';

/** The plugin endpoints that change a user's second factor. */
export const REAUTH_GATED_PATHS: ReadonlySet<string> = new Set([
  '/two-factor/enable',
  '/two-factor/disable',
  '/two-factor/generate-backup-codes',
]);

/** The sentence a stale passwordless session is refused with. */
export const REAUTH_REQUIRED_MESSAGE =
  `Sign in again to confirm it is you. Two-factor settings can be changed for ${REAUTH_WINDOW_MINUTES} minutes after you sign in.`;

/** A linked account, as Better Auth's adapter returns it. */
interface AccountRow {
  providerId: string;
  password?: string | null;
}

/** The session a request carries, reduced to what the gate reads. */
export interface ReauthSession {
  user: { id: string };
  session: { createdAt: Date | string | number };
}

/** The subset of the Better Auth `hooks.before` context this handler reads. */
export interface ReauthContext {
  path?: string;
  context: {
    internalAdapter: {
      findAccounts: (userId: string) => Promise<AccountRow[] | null | undefined>;
    };
  };
}

/**
 * Whether an account can prove itself with a password.
 *
 * @param accounts The user's Better Auth accounts.
 * @returns `true` when a credential account with a stored password exists — the same test the
 *   plugin's `shouldRequirePassword` applies.
 */
export function hasCredentialPassword(accounts: AccountRow[] | null | undefined): boolean {
  return Boolean(accounts?.some((account) => account.providerId === 'credential' && account.password));
}

/**
 * `hooks.before` handler: require a recent sign-in for a passwordless two-factor change.
 *
 * A no-op for every other path, for a request with no session (the endpoint's own session check
 * answers that), and for an account with a password.
 *
 * @param rawCtx The Better Auth middleware context.
 * @param readSession Reads the request's session; injectable for tests. Defaults to Better Auth's
 *   *authoritative* read, which goes to the database rather than the signed cookie cache, so a
 *   session that has been revoked cannot pass on the strength of a cached copy.
 * @param now The current time in milliseconds; injectable for tests.
 * @throws APIError `403` with code `REAUTH_REQUIRED` when the account has no password and its
 *   session is older than the re-authentication window.
 */
export async function twoFactorReauthHandler(
  rawCtx: unknown,
  readSession: (ctx: unknown) => Promise<ReauthSession | null> = (ctx) =>
    getAuthoritativeSessionFromCtx(ctx as never) as Promise<ReauthSession | null>,
  now: number = Date.now()
): Promise<void> {
  const ctx = rawCtx as ReauthContext;
  if (typeof ctx.path !== 'string' || !REAUTH_GATED_PATHS.has(ctx.path)) return;

  const current = await readSession(rawCtx);
  if (!current?.user?.id) return;

  if (hasCredentialPassword(await ctx.context.internalAdapter.findAccounts(current.user.id))) return;

  if (!isSessionFresh(current.session?.createdAt, now)) {
    throw new APIError('FORBIDDEN', { message: REAUTH_REQUIRED_MESSAGE, code: REAUTH_REQUIRED_CODE });
  }
}
