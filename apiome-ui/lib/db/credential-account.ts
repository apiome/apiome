/**
 * Credential-account dual-write helpers (OLO-10.5, #5000).
 *
 * The Better Auth migration relocates the credential password hash off `apiome.users.password` into
 * an `apiome.account` row with `providerId='credential'` (see V200 and
 * docs/BETTER_AUTH_MIGRATION.md §2.3). The one-time backfill in V200 handles users that already
 * exist; these helpers keep that relocated copy in sync for every password write that happens
 * afterwards, during the parallel-run window (§4, mitigation ii):
 *
 *   - {@link upsertCredentialAccountPassword} — a set/change of a usable password writes the same
 *     bcrypt hash into the credential account row.
 *   - {@link clearCredentialAccountPassword} — marking an account password-less removes its credential
 *     row, so an OAuth-only user never has a credential login they did not set.
 *
 * The legacy `users.password` column remains the source of truth for rollback until 10.14 (#5009); the
 * callers write it first and unconditionally, then invoke these helpers. Consequently the dual-write
 * is **best-effort**: a failure here (e.g. the `account` table not yet present on an older schema) is
 * logged but never thrown, so it cannot break the primary password write on the active NextAuth
 * engine. Pre-cutover verification (10.14 §4) reconciles any drift before Better Auth becomes
 * authoritative.
 *
 * This module deliberately has no `'use server'` directive: it is a plain internal DB utility invoked
 * by the server-action helpers (`helper.ts`, `admin-helper.ts`), not a server action itself.
 */

// `lib/db/db` is CommonJS (`module.exports = pool`); pulled in with require like every other consumer.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const crypto = require('crypto');

/** The literal `providerId` Better Auth uses for the email/password account row (design §2.3). */
export const CREDENTIAL_PROVIDER_ID = 'credential';

/**
 * Mirror a usable credential password hash into the user's `account` credential row.
 *
 * Idempotent per user: `UNIQUE("providerId","accountId")` (V199) means there is at most one
 * `('credential', userId)` row, so this upserts — inserting it on the first password set and updating
 * the hash on subsequent changes. The stored value is the **exact bcrypt hash** already written to
 * `users.password`; nothing is re-hashed, so the relocated copy always verifies identically.
 *
 * Best-effort: never throws. A blank/empty hash is treated as "no usable password" and clears the row
 * instead (delegates to {@link clearCredentialAccountPassword}).
 *
 * @param userId The user whose credential password changed (UUID).
 * @param passwordHash The bcrypt hash just written to `users.password`.
 * @returns Promise resolving when the mirror write completes (or is safely skipped).
 */
export async function upsertCredentialAccountPassword(
  userId: string,
  passwordHash: string | null | undefined
): Promise<void> {
  if (!userId) {
    return;
  }
  // An empty/absent hash is the OAuth-only "no usable credential" sentinel — remove the row instead of
  // storing a login that was never set.
  if (typeof passwordHash !== 'string' || passwordHash.length === 0) {
    await clearCredentialAccountPassword(userId);
    return;
  }

  try {
    await connectionPool.query(
      `INSERT INTO apiome.account ("id", "userId", "accountId", "providerId", "password", "createdAt", "updatedAt")
       VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
       ON CONFLICT ("providerId", "accountId")
       DO UPDATE SET "password" = EXCLUDED."password", "updatedAt" = CURRENT_TIMESTAMP`,
      [crypto.randomUUID(), userId, userId, CREDENTIAL_PROVIDER_ID, passwordHash]
    );
  } catch (error) {
    // Best-effort: log and swallow so a missing/older `account` table never blocks the password write.
    console.error(
      `[credential-account] Failed to mirror credential password for user ${userId} (users.password write is authoritative):`,
      error instanceof Error ? error.message : error
    );
  }
}

/**
 * Remove a user's credential `account` row, marking them password-less on the Better Auth model.
 *
 * Mirrors `clearUserPassword` (which sets `users.password = ''` — the "no usable credential"
 * sentinel). Deleting the row is the Better Auth equivalent: no credential account means no
 * email/password sign-in, which is exactly how the last-sign-in-method guard (OLO-2.4) must read an
 * OAuth-only account. Best-effort: never throws.
 *
 * @param userId The user to mark password-less (UUID).
 * @returns Promise resolving when the row is removed (or the no-op is safely skipped).
 */
export async function clearCredentialAccountPassword(userId: string): Promise<void> {
  if (!userId) {
    return;
  }
  try {
    await connectionPool.query(
      `DELETE FROM apiome.account WHERE "userId" = $1 AND "providerId" = $2`,
      [userId, CREDENTIAL_PROVIDER_ID]
    );
  } catch (error) {
    console.error(
      `[credential-account] Failed to clear credential account for user ${userId} (users.password clear is authoritative):`,
      error instanceof Error ? error.message : error
    );
  }
}
