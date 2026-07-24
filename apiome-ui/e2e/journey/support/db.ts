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
import { hash as bcryptHash } from 'bcrypt';
import { randomBytes, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { databaseUrl } from './env';

/** bcrypt cost the app hashes/verifies credential passwords at (`better-auth-credentials.ts`). */
const BCRYPT_COST = 10;

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
 * Insert a verified, enabled user with a real, usable credential password (OLO-10.13).
 *
 * Unlike {@link seedVerifiedUser} (which writes password garbage so the account is OAuth-only), this
 * writes a bcrypt hash to BOTH password homes the migrated stack keeps in sync (OLO-10.5): the
 * legacy `users.password` source of truth AND an `apiome.account` credential row
 * (`"providerId"='credential'`, `"accountId"` = the user's own id) that Better Auth's `signIn.email`
 * verifies against. So the seeded user can sign in through the login page's email/password form on the
 * Better Auth engine. Seeded `verified=true` because Better Auth's `requireEmailVerification` refuses
 * an unverified credential sign-in.
 *
 * @param email Canonical email address for the user.
 * @param password Plaintext password to hash and store.
 * @param name Display name.
 * @returns The new user's id.
 */
export async function seedCredentialUser(
  email: string,
  password: string,
  name: string
): Promise<string> {
  const canonicalEmail = email.toLowerCase();
  const passwordHash = await bcryptHash(password, BCRYPT_COST);
  const pool = getPool();

  const userResult = await pool.query(
    `INSERT INTO apiome.users (name, email, password, verified, enabled)
     VALUES ($1, $2, $3, true, true)
     RETURNING id`,
    [name, canonicalEmail, passwordHash]
  );
  const userId = userResult.rows[0].id as string;

  // The Better Auth credential account: self-owned (accountId = the user id), providerId 'credential',
  // same bcrypt hash, verified. ON CONFLICT keeps re-runs idempotent (UNIQUE providerId+accountId).
  await pool.query(
    `INSERT INTO apiome.account
       ("id", "userId", "accountId", "providerId", "password", provider_email, email_verified)
     VALUES ($1, $2, $3, 'credential', $4, $5, true)
     ON CONFLICT ("providerId", "accountId") DO UPDATE SET "password" = EXCLUDED."password"`,
    [randomUUID(), userId, userId, passwordHash, canonicalEmail]
  );
  return userId;
}

/**
 * Path to the canonical multi-tenant dev-seed fixture (OLO-6.4, #4221), resolved relative to
 * this file so it works regardless of the working directory the tests run from.
 */
const MULTITENANT_SEED = resolve(
  __dirname,
  '../../../../apiome-db/seed/dev/007_multitenant.sql'
);

/** The three tenants the multi-tenant fixture creates, in the order the switcher lists them. */
export const MULTITENANT_FIXTURE = {
  user: { email: 'grace@example.com', name: 'Grace Hopper' },
  tenants: [
    { slug: 'aurora-labs', name: 'Aurora Labs', role: 'owner', license: 'Free' },
    { slug: 'borealis-studio', name: 'Borealis Studio', role: 'editor', license: 'Paid' },
    { slug: 'cascade-foundation', name: 'Cascade Foundation', role: 'viewer', license: 'Sponsor' },
  ],
} as const;

/**
 * Apply the multi-tenant dev-seed fixture (`apiome-db/seed/dev/007_multitenant.sql`): one verified
 * user (Grace) in three tenants with diverging roles (owner/editor/viewer) and license tiers
 * (Free/Paid/Sponsor). The SQL is idempotent (fixed ids + ON CONFLICT), so running it against a
 * shared stack is safe and repeatable. Exercising the *actual* seed file — not a hand-built copy —
 * keeps this test honest about "fixtures in seed/dev".
 */
export async function seedMultiTenantFixture(): Promise<void> {
  const sql = await readFile(MULTITENANT_SEED, 'utf8');
  await getPool().query(sql);
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
 * Whether the user owning this email has 2FA enabled, and how many `two_factor` rows they hold
 * (OLO-10.13). The TOTP secret and backup codes are ciphertext at rest (V201 / plugin-encrypted), so
 * the journey asserts only the enabled flag + row existence, not plaintext.
 *
 * @param email The user's email address.
 * @returns `{ enabled, rows }` — `enabled` is `users."twoFactorEnabled"`, `rows` is the count of the
 *   user's `apiome.two_factor` rows.
 */
export async function getTwoFactorState(email: string): Promise<{ enabled: boolean; rows: number }> {
  const result = await getPool().query(
    `SELECT u."twoFactorEnabled" AS enabled,
            (SELECT COUNT(*)::int FROM apiome.two_factor tf WHERE tf."userId" = u.id) AS rows
       FROM apiome.users u
      WHERE LOWER(u.email) = $1`,
    [email.toLowerCase()]
  );
  if (result.rowCount === 0) {
    return { enabled: false, rows: 0 };
  }
  return { enabled: result.rows[0].enabled === true, rows: result.rows[0].rows as number };
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
