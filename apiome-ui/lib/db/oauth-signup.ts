import { sealTokenOrNull, unsealToken } from '../auth/linked-account-token-crypto';

const crypto = require('crypto');
const connectionPool = require('./db');

const PENDING_TTL_MS = 60 * 60 * 1000;
const ONE_TIME_TTL_MS = 15 * 60 * 1000;

export type OauthSignupPendingRow = {
  id: string;
  provider: string;
  provider_account_id: string;
  email: string;
  account_json: Record<string, unknown>;
  profile_json: Record<string, unknown>;
  expires_at: string;
};

function parseJsonObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  return {};
}

/** The provider credentials inside a staged `account_json` that are sealed at rest (#4960). */
const PENDING_TOKEN_FIELDS = ['access_token', 'refresh_token', 'id_token'] as const;

/**
 * Seal the provider tokens of a staged OAuth account before it is written (#4960).
 *
 * @param account The provider account payload from the OAuth callback.
 * @returns A copy whose token fields hold ciphertext. A token that cannot be sealed (encryption not
 *   configured) is dropped rather than staged in plaintext; sign-up still completes without it.
 */
function sealPendingAccount(account: Record<string, unknown>): Record<string, unknown> {
  const sealed: Record<string, unknown> = { ...account };
  for (const field of PENDING_TOKEN_FIELDS) {
    if (!(field in sealed)) continue;
    const value = sealed[field];
    sealed[field] = typeof value === 'string' ? sealTokenOrNull(value) : null;
  }
  return sealed;
}

/**
 * Restore the plaintext provider tokens of a staged OAuth account after it is read (#4960).
 *
 * @param account The stored `account_json` object.
 * @returns A copy whose token fields hold the plaintext tokens (`null` when absent or undecryptable).
 */
function unsealPendingAccount(account: Record<string, unknown>): Record<string, unknown> {
  const unsealed: Record<string, unknown> = { ...account };
  for (const field of PENDING_TOKEN_FIELDS) {
    if (field in unsealed) unsealed[field] = unsealToken(unsealed[field]);
  }
  return unsealed;
}

export async function upsertOauthSignupPending(
  provider: string,
  providerAccountId: string,
  email: string,
  account: Record<string, unknown>,
  profile: Record<string, unknown>
): Promise<{ id: string }> {
  const expiresAt = new Date(Date.now() + PENDING_TTL_MS);
  const result = await connectionPool.query(
    `INSERT INTO apiome.oauth_signup_pending (
       provider, provider_account_id, email, account_json, profile_json, expires_at
     ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
     ON CONFLICT (provider, provider_account_id) DO UPDATE SET
       email = EXCLUDED.email,
       account_json = EXCLUDED.account_json,
       profile_json = EXCLUDED.profile_json,
       expires_at = EXCLUDED.expires_at
     RETURNING id`,
    [provider, providerAccountId, email, JSON.stringify(sealPendingAccount(account)), JSON.stringify(profile), expiresAt]
  );
  return { id: result.rows[0].id };
}

export async function getOauthSignupPendingById(id: string): Promise<OauthSignupPendingRow | null> {
  const result = await connectionPool.query(
    `SELECT id, provider, provider_account_id, email, account_json, profile_json, expires_at
     FROM apiome.oauth_signup_pending WHERE id = $1`,
    [id]
  );
  if (result.rowCount === 0) return null;
  const row = result.rows[0];
  if (new Date(row.expires_at) < new Date()) return null;
  return {
    id: row.id,
    provider: row.provider,
    provider_account_id: row.provider_account_id,
    email: row.email,
    account_json: unsealPendingAccount(parseJsonObject(row.account_json)),
    profile_json: parseJsonObject(row.profile_json),
    expires_at: row.expires_at,
  };
}

export async function deleteOauthSignupPendingById(id: string): Promise<void> {
  await connectionPool.query(`DELETE FROM apiome.oauth_signup_pending WHERE id = $1`, [id]);
}

export async function insertAuthOneTimeCode(userId: string, tenantId: string | null): Promise<string> {
  const id = crypto.randomUUID();
  const expiresAt = new Date(Date.now() + ONE_TIME_TTL_MS);
  await connectionPool.query(
    `INSERT INTO apiome.auth_one_time_codes (id, user_id, tenant_id, expires_at) VALUES ($1, $2, $3, $4)`,
    [id, userId, tenantId, expiresAt]
  );
  return id;
}

export type ConsumedOneTimeCode = { userId: string; tenantId: string | null };

export async function consumeAuthOneTimeCode(code: string): Promise<ConsumedOneTimeCode | null> {
  const result = await connectionPool.query(
    `DELETE FROM apiome.auth_one_time_codes
     WHERE id = $1 AND expires_at > CURRENT_TIMESTAMP
     RETURNING user_id, tenant_id`,
    [code]
  );
  if (result.rowCount === 0) return null;
  return { userId: result.rows[0].user_id, tenantId: result.rows[0].tenant_id };
}

export async function insertFreeTierEntitlements(userId: string): Promise<void> {
  await connectionPool.query(
    `INSERT INTO apiome.user_entitlements (user_id, plan_code, max_tenants, max_projects, max_versions, license_id)
     SELECT $1, l.license_type, 1, 1, 3, l.id
     FROM apiome.licenses l
     WHERE l.name = 'Free' AND l.license_type = 'free'
     LIMIT 1
     ON CONFLICT (user_id) DO NOTHING`,
    [userId]
  );
}
