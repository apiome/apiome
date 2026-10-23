/**
 * Database calls for email sign-up verification (SGN-1.1, #5650; table V313).
 *
 * Deliberately **not** a `'use server'` module: these functions take user ids and token hashes
 * the caller has already authorised, so they must never become client-callable server actions.
 * They are reached only through `lib/auth/email-signup-actions.ts`, which validates its input.
 */

import {
  classifyVerificationToken,
  type VerificationTokenState,
} from '../auth/email-signup';

// `lib/db/db` is a CommonJS module (`module.exports = pool`), like every other lib/db consumer.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

/** The facts about an existing account the sign-up flow needs. */
export interface SignupAccount {
  id: string;
  name: string;
  email: string;
  verified: boolean;
  enabled: boolean;
}

/**
 * The live (not soft-deleted) account holding a canonical email, if any.
 *
 * Matches case-insensitively, as every other email lookup does (V180 canonical storage).
 *
 * @param canonicalEmail Trimmed, lowercased address.
 * @returns The account, or `null`.
 */
export async function findSignupAccount(canonicalEmail: string): Promise<SignupAccount | null> {
  const result = await connectionPool.query(
    `SELECT id, name, email, verified, enabled
       FROM apiome.users
      WHERE lower(email) = $1 AND deleted_at IS NULL
      LIMIT 1`,
    [canonicalEmail]
  );
  if (!result.rowCount) return null;
  const row = result.rows[0];
  return {
    id: row.id,
    name: row.name,
    email: row.email,
    verified: Boolean(row.verified),
    enabled: Boolean(row.enabled),
  };
}

/**
 * Store a new verification token for a user, retiring their unused ones.
 *
 * One transaction, so a user never has two live links: the newest email is the one that works.
 *
 * @param userId The unverified user.
 * @param tokenHash From `generateVerificationToken`.
 * @param expiresAt When the link stops working.
 */
export async function issueVerificationToken(
  userId: string,
  tokenHash: string,
  expiresAt: Date
): Promise<void> {
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    await client.query(
      `DELETE FROM apiome.email_verification_token WHERE user_id = $1 AND used_at IS NULL`,
      [userId]
    );
    await client.query(
      `INSERT INTO apiome.email_verification_token (user_id, token_hash, expires_at)
       VALUES ($1, $2, $3)`,
      [userId, tokenHash, expiresAt]
    );
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

/** What redeeming a link did. */
export interface RedeemResult {
  state: VerificationTokenState;
  /** The verified user, only when `state` is `valid`. */
  userId: string | null;
}

/**
 * Redeem a verification link: mark it used and the account verified, atomically.
 *
 * The row is locked (`FOR UPDATE`) so two simultaneous clicks cannot both succeed. A disabled or
 * soft-deleted account is treated as an invalid link, never verified.
 *
 * @param tokenHash Hash of the token from the link.
 * @param now Current time; injectable for tests.
 * @returns The link's state and, when valid, the user it verified.
 */
export async function redeemVerificationToken(
  tokenHash: string,
  now: Date = new Date()
): Promise<RedeemResult> {
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    const found = await client.query(
      `SELECT t.id, t.user_id, t.expires_at, t.used_at
         FROM apiome.email_verification_token t
         JOIN apiome.users u ON u.id = t.user_id
        WHERE t.token_hash = $1 AND u.deleted_at IS NULL AND u.enabled
        FOR UPDATE OF t`,
      [tokenHash]
    );
    const row = found.rowCount
      ? {
          expiresAt: new Date(found.rows[0].expires_at),
          usedAt: found.rows[0].used_at ? new Date(found.rows[0].used_at) : null,
        }
      : null;
    const state = classifyVerificationToken(row, now);
    if (state !== 'valid') {
      await client.query('ROLLBACK');
      return { state, userId: null };
    }
    const userId: string = found.rows[0].user_id;
    await client.query(
      `UPDATE apiome.email_verification_token SET used_at = $2 WHERE id = $1`,
      [found.rows[0].id, now]
    );
    await client.query(
      `UPDATE apiome.users SET verified = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = $1`,
      [userId]
    );
    await client.query('COMMIT');
    return { state, userId };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
