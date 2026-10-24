/**
 * Database calls for email sign-up verification (SGN-1.1, #5650; table V313).
 *
 * Deliberately **not** a `'use server'` module: these functions take user ids and token hashes
 * the caller has already authorised, so they must never become client-callable server actions.
 * They are reached only through `lib/auth/email-signup-actions.ts`, which validates its input.
 */

import crypto from 'crypto';

import {
  classifyVerificationToken,
  type VerificationTokenState,
} from '../auth/email-signup';

// `lib/db/db` is a CommonJS module (`module.exports = pool`), like every other lib/db consumer.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const bcrypt = require('bcrypt');

/** The Better Auth provider id of the email-and-password login (`lib/db/credential-account.ts`). */
const CREDENTIAL_PROVIDER_ID = 'credential';

/**
 * What a sign-up submitted with its link: the password (as a bcrypt hash) and display name.
 *
 * A link is bound to the sign-up that produced it. Opening it asks for that password, and on a match
 * the hash becomes the account's credential — so a link sent because someone *else* signed up with
 * your address cannot leave their password on your account (pre-hijacking, RC6 security review).
 */
export interface PendingSignup {
  /** bcrypt hash of the submitted password. */
  passwordHash: string;
  /** The submitted display name. */
  name: string;
}

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
 * @param pending The password and name submitted with this sign-up; omitted only for a link issued
 *   without one (it then falls back to the stored password when redeemed).
 */
export async function issueVerificationToken(
  userId: string,
  tokenHash: string,
  expiresAt: Date,
  pending: PendingSignup | null = null
): Promise<void> {
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    await client.query(
      `DELETE FROM apiome.email_verification_token WHERE user_id = $1 AND used_at IS NULL`,
      [userId]
    );
    await client.query(
      `INSERT INTO apiome.email_verification_token
         (user_id, token_hash, expires_at, pending_password_hash, pending_name)
       VALUES ($1, $2, $3, $4, $5)`,
      [userId, tokenHash, expiresAt, pending?.passwordHash ?? null, pending?.name ?? null]
    );
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

/**
 * The pending sign-up of a user's newest link, if any — what a resend carries forward, since the
 * resend form never sees the password.
 *
 * @param userId The unverified user.
 * @returns The newest link's pending password and name, or `null` when no link carries one.
 */
export async function findPendingSignup(userId: string): Promise<PendingSignup | null> {
  const result = await connectionPool.query(
    `SELECT pending_password_hash, pending_name
       FROM apiome.email_verification_token
      WHERE user_id = $1 AND pending_password_hash IS NOT NULL
      ORDER BY created_at DESC
      LIMIT 1`,
    [userId]
  );
  if (!result.rowCount) return null;
  const row = result.rows[0];
  return { passwordHash: row.pending_password_hash, name: row.pending_name ?? '' };
}

/** What redeeming a link did. */
export interface RedeemResult {
  /** The link's state, or `password-mismatch` when the password is not the one this sign-up set. */
  state: VerificationTokenState | 'password-mismatch';
  /** The verified user, only when `state` is `valid`. */
  userId: string | null;
}

/**
 * Redeem a verification link: check the password, then verify the account, atomically.
 *
 * The link proves the person reads the address's mail; the password proves they made *this*
 * sign-up. On a match, in one transaction:
 *
 * - the link is marked used and the account verified;
 * - the link's password hash becomes the account's only credential — `users.password` **and** the
 *   Better Auth `account` row — and its name the account's name, replacing whatever an earlier,
 *   unconfirmed sign-up for the address stored there;
 * - the user's other unused links are deleted and every session is revoked.
 *
 * A wrong password leaves everything as it was (the link stays usable). The row is locked
 * (`FOR UPDATE`) so two simultaneous clicks cannot both succeed. A disabled or soft-deleted account
 * is treated as an invalid link, never verified. A link issued before V318 carries no pending hash
 * and is checked against the stored password instead.
 *
 * @param tokenHash Hash of the token from the link.
 * @param password The password the person entered.
 * @param now Current time; injectable for tests.
 * @returns The link's state and, when valid, the user it verified.
 */
export async function redeemVerificationToken(
  tokenHash: string,
  password: string,
  now: Date = new Date()
): Promise<RedeemResult> {
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    const found = await client.query(
      `SELECT t.id, t.user_id, t.expires_at, t.used_at, t.pending_password_hash, t.pending_name,
              u.password AS stored_password
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
    const link = found.rows[0];
    const userId: string = link.user_id;
    const passwordHash: string | null = link.pending_password_hash ?? link.stored_password ?? null;
    const matches =
      typeof passwordHash === 'string' && passwordHash.length > 0 && (await bcrypt.compare(password, passwordHash));
    if (!matches) {
      await client.query('ROLLBACK');
      return { state: 'password-mismatch', userId: null };
    }
    await client.query(
      `UPDATE apiome.email_verification_token SET used_at = $2 WHERE id = $1`,
      [link.id, now]
    );
    await client.query(
      `UPDATE apiome.users
          SET verified = TRUE,
              password = $2,
              name = COALESCE(NULLIF($3, ''), name),
              updated_at = CURRENT_TIMESTAMP
        WHERE id = $1`,
      [userId, passwordHash, link.pending_name ?? null]
    );
    // The Better Auth credential row is what email-and-password sign-in checks; it must hold the
    // confirmed hash, not one an earlier sign-up for this address left behind. Not best-effort: a
    // failure here rolls the whole verification back.
    await client.query(
      `INSERT INTO apiome.account ("id", "userId", "accountId", "providerId", "password", "createdAt", "updatedAt")
       VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
       ON CONFLICT ("providerId", "accountId")
       DO UPDATE SET "password" = EXCLUDED."password", "updatedAt" = CURRENT_TIMESTAMP`,
      [crypto.randomUUID(), userId, userId, CREDENTIAL_PROVIDER_ID, passwordHash]
    );
    await client.query(
      `DELETE FROM apiome.email_verification_token WHERE user_id = $1 AND used_at IS NULL`,
      [userId]
    );
    await client.query(`DELETE FROM apiome.session WHERE "userId" = $1`, [userId]);
    await client.query('COMMIT');
    return { state, userId };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
