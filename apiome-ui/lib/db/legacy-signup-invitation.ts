/**
 * Database calls for inviting the people left in the retired sign-up request queue (SGN-1.3,
 * #5652; tables V009 `apiome.signup`, read-only since V314, and V314
 * `apiome.legacy_signup_invitation`).
 *
 * Deliberately **not** a `'use server'` module: nothing here may become a client-callable server
 * action. It is reached only from the startup sweep in `lib/auth/legacy-signup-invitations.ts`.
 */

// `lib/db/db` is a CommonJS module (`module.exports = pool`), like every other lib/db consumer.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

/** Postgres "undefined_table": the migrations have not run yet (or the queue was dropped). */
const UNDEFINED_TABLE = '42P01';

/** One queued request the sweep has not handled yet. */
export interface LegacySignupRequest {
  /** The address exactly as the queue holds it (the ledger key). */
  emailAddress: string;
  /** The name typed on the old request form. */
  name: string;
}

/** How a queued address was handled, as recorded in the ledger. */
export type LegacySignupInvitationOutcome = 'sent' | 'account_exists';

/**
 * The queued requests with no ledger row yet, oldest first.
 *
 * @returns The requests; empty when either table is missing (before V314, or after the queue is
 *   dropped), so the sweep is a no-op rather than an error.
 */
export async function listUninvitedLegacySignups(): Promise<LegacySignupRequest[]> {
  try {
    const result = await connectionPool.query(
      `SELECT s.email_address, s.name
         FROM apiome.signup s
        WHERE NOT EXISTS (
                SELECT 1 FROM apiome.legacy_signup_invitation i
                 WHERE i.email_address = s.email_address)
        ORDER BY s.signup_date ASC NULLS LAST`
    );
    return result.rows.map((row: { email_address: string; name: string }) => ({
      emailAddress: row.email_address,
      name: row.name,
    }));
  } catch (error) {
    if ((error as { code?: string })?.code === UNDEFINED_TABLE) return [];
    throw error;
  }
}

/**
 * Claim a queued address for the sweep by recording its outcome.
 *
 * The ledger's primary key makes the claim atomic: when several app replicas start together, only
 * one gets `true` for each address, so each invitation is sent once.
 *
 * @param emailAddress The address as the queue holds it.
 * @param outcome What this sweep is about to do with it.
 * @returns `true` when this caller won the claim; `false` when the address was already handled.
 */
export async function claimLegacySignupInvitation(
  emailAddress: string,
  outcome: LegacySignupInvitationOutcome
): Promise<boolean> {
  const result = await connectionPool.query(
    `INSERT INTO apiome.legacy_signup_invitation (email_address, outcome)
     VALUES ($1, $2)
     ON CONFLICT (email_address) DO NOTHING
     RETURNING email_address`,
    [emailAddress, outcome]
  );
  return Boolean(result.rowCount);
}

/**
 * Give up a claim after its email failed, so the next startup tries again.
 *
 * @param emailAddress The address as the queue holds it.
 */
export async function releaseLegacySignupInvitation(emailAddress: string): Promise<void> {
  await connectionPool.query(
    `DELETE FROM apiome.legacy_signup_invitation WHERE email_address = $1 AND outcome = 'sent'`,
    [emailAddress]
  );
}
