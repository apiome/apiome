/**
 * Direct-database helpers for the OLO-7.4 journey suite (#4226).
 *
 * The journey mostly drives the browser, but two things need the database directly:
 *
 *   1. Seeding preconditions the product cannot create through the UI alone — a verified
 *      user with **zero tenant memberships** (the FirstTenantOnboardingGuard state, which
 *      in production arises from offboarding/administration, not from any signup path)
 *      and pre-existing accounts to invite against the seat limit.
 *   2. Asserting the OLO-1.3 invariants at the storage layer — "same email via a second
 *      provider links, never duplicates" is only provable by counting `users` rows and
 *      reading `external_auth_providers`.
 *
 * Uses the same `DATABASE_URL` as the app under test (see `env.ts`).
 */
import { Pool } from 'pg';
import { randomBytes } from 'node:crypto';
import { databaseUrl } from './env';

let pool: Pool | null = null;

/** Lazily open the shared connection pool. */
function getPool(): Pool {
  if (!pool) {
    pool = new Pool({ connectionString: databaseUrl(), max: 2 });
  }
  return pool;
}

/**
 * Close the pool. Call from `test.afterAll` so the worker exits cleanly.
 */
export async function closeDb(): Promise<void> {
  await pool?.end();
  pool = null;
}

/**
 * Insert a verified, enabled user with no tenant memberships.
 *
 * The password is random garbage (not a bcrypt hash), so the account is only reachable
 * via OAuth — exactly the shape the zero-tenant wizard leg needs.
 *
 * @param email Canonical email address for the user.
 * @param name Display name.
 * @returns The new user's id.
 */
export async function seedVerifiedUser(email: string, name: string): Promise<string> {
  const result = await getPool().query(
    `INSERT INTO apiome.users (name, email, password, verified, enabled)
     VALUES ($1, $2, $3, true, true)
     RETURNING id`,
    [name, email.toLowerCase(), randomBytes(32).toString('hex')]
  );
  return result.rows[0].id as string;
}

/**
 * Count live user rows for an email — the "never duplicates" invariant reads this.
 *
 * @param email Address to count (canonicalized).
 * @returns Number of matching `apiome.users` rows.
 */
export async function countUsersByEmail(email: string): Promise<number> {
  const result = await getPool().query(
    'SELECT COUNT(*)::int AS n FROM apiome.users WHERE LOWER(email) = $1',
    [email.toLowerCase()]
  );
  return result.rows[0].n as number;
}

/**
 * The provider slugs linked to the user owning this email, sorted.
 *
 * @param email The user's email address.
 * @returns e.g. `['github', 'gitlab']`; empty when no user or no identities exist.
 */
export async function listLinkedProviders(email: string): Promise<string[]> {
  const result = await getPool().query(
    `SELECT eap.provider
       FROM apiome.external_auth_providers eap
       JOIN apiome.users u ON u.id = eap.user_id
      WHERE LOWER(u.email) = $1
      ORDER BY eap.provider`,
    [email.toLowerCase()]
  );
  return result.rows.map((row: { provider: string }) => row.provider);
}
