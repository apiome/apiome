/**
 * Secret generation/hashing that is byte-for-byte compatible with the rest of the platform:
 *  - API keys match `apiome-ui` (lib/db/helper.ts) and are validated by `apiome-rest`
 *    (`Database.validate_api_key`): `sk_` + 32 random bytes hex, prefix = first 12 chars + '...',
 *    hash = bcrypt(key, 10).
 *  - Passwords use bcrypt(pw, 10), the same scheme the UI and REST verify with.
 */

import crypto from "node:crypto";

import bcrypt from "bcrypt";

/** Cost factor used everywhere in the platform for bcrypt hashing. */
export const BCRYPT_ROUNDS = 10;

export const API_KEY_PREFIX = "sk_";

/** Generate a plaintext API key (`sk_` + 64 hex chars). Shown to the operator exactly once. */
export function generateApiKey(): string {
  return API_KEY_PREFIX + crypto.randomBytes(32).toString("hex");
}

/**
 * The `key_prefix` stored alongside the hash and used for lookup by the REST service:
 * first 12 characters of the key plus a literal `...` (e.g. `sk_abcd1234...`).
 */
export function apiKeyPrefix(apiKey: string): string {
  return `${apiKey.slice(0, 12)}...`;
}

/** bcrypt hash of the full API key (REST verifies with `bcrypt.checkpw(rawKey, key_hash)`). */
export function hashApiKey(apiKey: string): Promise<string> {
  return bcrypt.hash(apiKey, BCRYPT_ROUNDS);
}

/** bcrypt hash of a user password. */
export function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, BCRYPT_ROUNDS);
}

/** Strong random password for break-glass user creation; printed once to the operator. */
export function generatePassword(): string {
  return `${crypto.randomBytes(18).toString("base64url")}!Aa1`;
}
