/**
 * Refuse a session for an account that is disabled or deleted, whatever the sign-in method.
 *
 * Provider and SSO sign-ins already refuse these accounts in the account-resolution engine
 * (`account-resolution.ts`, `rejectionForUser`). Email-and-password sign-in runs inside Better Auth,
 * which knows nothing of `users.enabled` or `users.deleted_at`. Without this guard, an administrator's
 * **Disable User** or **Delete User** did not stop a password sign-in. It runs as Better Auth's
 * `databaseHooks.session.create.before`, so it covers every endpoint that creates a session.
 *
 * A refused password sign-in shows the login page's usual "credentials" message, so the guard does
 * not tell anyone whether an address has a disabled account. A provider callback is redirected to
 * the `account-disabled` login error, as the engine would have done.
 */

import { APIError } from 'better-auth/api';

import { AUTH_ERROR_CODES, loginErrorRedirect } from './account-resolution';
import { setOauthRedirectOverride } from './better-auth-oauth-providers';

// The pool is a CommonJS module, loaded the way the rest of lib/ loads it.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('../db/db');

/** What the guard needs to know about an account. */
export interface AccountState {
  enabled: boolean;
  deleted: boolean;
}

/** Injectable reader, for tests. */
export interface AccountStateDeps {
  readAccountState: (userId: string) => Promise<AccountState | null>;
}

/**
 * Read an account's state.
 *
 * @param userId The user's id.
 * @returns The state, or null when no user has the id.
 */
async function readAccountState(userId: string): Promise<AccountState | null> {
  const result = await connectionPool.query(
    'SELECT enabled, deleted_at FROM apiome.users WHERE id = $1',
    [userId]
  );
  if (!result.rowCount) return null;
  const row = result.rows[0];
  return { enabled: Boolean(row.enabled), deleted: row.deleted_at != null };
}

const defaultDeps: AccountStateDeps = { readAccountState };

/**
 * `databaseHooks.session.create.before`: refuse a session for a disabled, deleted or missing account.
 *
 * @param session The session Better Auth is about to create.
 * @param deps Injectable dependencies.
 * @returns undefined to admit. A refusal throws a `FORBIDDEN` APIError with code `account-disabled`.
 */
export async function accountStateSessionCreateBefore(
  session: Record<string, unknown>,
  deps: AccountStateDeps = defaultDeps
): Promise<undefined> {
  const userId = typeof session?.userId === 'string' ? session.userId : null;
  if (!userId) return undefined;
  const state = await deps.readAccountState(userId);
  if (state && state.enabled && !state.deleted) return undefined;
  const code = AUTH_ERROR_CODES.ACCOUNT_DISABLED;
  setOauthRedirectOverride(loginErrorRedirect(code));
  throw new APIError('FORBIDDEN', { code, message: code });
}
