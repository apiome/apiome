/**
 * Envelope encryption-at-rest for linked-account tokens (OLO-7.3 follow-up, #4960).
 *
 * A linked account (`apiome.external_auth_providers`) holds the OAuth access / refresh token a
 * provider issued at sign-in, or a personal access token the user pasted in. Those are live
 * credentials to the user's external repositories, so they are stored as **ciphertext only**: a
 * database read (backup leak, replica, SQL injection) must not yield a usable token.
 *
 * **Two services share this vault.** apiome-ui seals a token when it writes the row and unseals it
 * for its own GitHub proxy routes; apiome-rest unseals it when it scans or imports a repository.
 * This module is a byte-compatible port of `apiome-rest/src/app/linked_account_token_crypto.py`
 * (which configures `app.envelope_crypto.EnvelopeCipher`), and both services must be given the same
 * key map. The shared vectors in `tests/fixtures/linked-account-token-vectors.json` pin the format
 * on both sides — change either implementation and the other side's test fails.
 *
 * Scheme — AES-256-GCM envelope encryption:
 *
 * - a per-token random **data key (DEK)** encrypts the JSON payload `{"token": "<the token>"}`;
 * - a long-lived **master key**, supplied from the environment, wraps that DEK;
 * - the master key's **version** is stored with the value and bound into the additional
 *   authenticated data (`OLAT:v<version>`) of both encryptions, so a value cannot be re-tagged to
 *   another key or moved to another vault.
 *
 * Blob framing (identical to the Python side):
 *
 *     MAGIC(4) | FORMAT(1) | wrap_nonce(12) | wrapped_dek(48) | payload_nonce(12) | ciphertext(>=16)
 *
 * Stored form — the columns stay `TEXT` and a sealed value is self-describing:
 *
 *     enc:v1:<key_version>:<base64(blob)>
 *
 * A value *without* the prefix is a **legacy plaintext** token written before V275;
 * {@link unsealToken} returns it unchanged so an upgraded deployment keeps working until
 * apiome-rest's `python -m app.seal_linked_account_tokens` has converted it.
 *
 * Key configuration (environment, identical in apiome-ui and apiome-rest):
 *
 * - `APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS` — a JSON object mapping an integer key-version to
 *   a base64-encoded 32-byte key, e.g. `{"1": "<base64 key>"}`.
 * - `APIOME_LINKED_ACCOUNT_TOKEN_ACTIVE_KEY_VERSION` — which version new tokens are sealed under.
 *   Optional; defaults to the highest version present.
 *
 * Failure policy:
 *
 * - **Sealing fails closed.** With no key configured {@link sealToken} throws; a token is never
 *   written in plaintext as a fallback. Callers either store nothing ({@link sealTokenOrNull}) or
 *   refuse the request.
 * - **Unsealing fails safe.** A sealed value that cannot be opened yields `null` — "no token" —
 *   never the ciphertext.
 * - **Secrets never logged.** Messages carry only the key-version and the shape of the failure.
 *
 * Server-only: it reads key material from `process.env` and must never be imported by a client
 * component.
 */

import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';

/** The environment variable both services read the key map from. */
export const KEYS_SETTING = 'APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS';

/** The environment variable naming the key-version new tokens are sealed under. */
export const ACTIVE_VERSION_SETTING = 'APIOME_LINKED_ACCOUNT_TOKEN_ACTIVE_KEY_VERSION';

/**
 * Opens every sealed column value. No provider issues a token beginning with it, so its presence
 * is what tells a sealed value from a legacy plaintext one.
 */
export const SEALED_PREFIX = 'enc:v1:';

/** `OLAT` = OAuth Linked-Account Token: opens every blob and feeds the AAD. */
const MAGIC = Buffer.from('OLAT', 'ascii');
const FORMAT_VERSION = 1;
const NONCE_LEN = 12;
const KEY_LEN = 32;
const TAG_LEN = 16;
const WRAPPED_DEK_LEN = KEY_LEN + TAG_LEN;
const HEADER_LEN = MAGIC.length + 1;
/** Smallest legal blob: header + wrap nonce + wrapped DEK + payload nonce + an empty payload's tag. */
const MIN_BLOB_LEN = HEADER_LEN + NONCE_LEN + WRAPPED_DEK_LEN + NONCE_LEN + TAG_LEN;
const ALGORITHM = 'aes-256-gcm';

/** The environment shape the key material is read from (`process.env` in production). */
export type TokenCryptoEnv = Record<string, string | undefined>;

/**
 * Thrown when a token cannot be sealed: encryption is not configured, or the key map is malformed.
 * The message never contains secret material, so it is safe to log.
 */
export class LinkedAccountTokenEncryptionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'LinkedAccountTokenEncryptionError';
  }
}

/**
 * Decode one base64 master key, requiring exactly 32 bytes (AES-256).
 *
 * @param value The configured key (standard or URL-safe base64).
 * @param version The key-version it was configured under (used only in the error message).
 * @returns The 32 raw key bytes.
 * @throws LinkedAccountTokenEncryptionError If the value does not decode to 32 bytes.
 */
function decodeMasterKey(value: string, version: number): Buffer {
  const candidate = value.trim();
  if (!/^[A-Za-z0-9+/_-]+={0,2}$/.test(candidate)) {
    throw new LinkedAccountTokenEncryptionError(`master key for version ${version} is not valid base64`);
  }
  const raw = Buffer.from(candidate.replace(/-/g, '+').replace(/_/g, '/'), 'base64');
  if (raw.length !== KEY_LEN) {
    throw new LinkedAccountTokenEncryptionError(
      `master key for version ${version} must decode to ${KEY_LEN} bytes (AES-256), got ${raw.length}`
    );
  }
  return raw;
}

/**
 * Parse the configured key map into `version → 32-byte key`.
 *
 * @param env The environment to read from.
 * @returns Every configured master key by version; empty when nothing is configured.
 * @throws LinkedAccountTokenEncryptionError If the value is present but malformed.
 */
export function loadKeyMap(env: TokenCryptoEnv = process.env): Map<number, Buffer> {
  const raw = env[KEYS_SETTING];
  const keys = new Map<number, Buffer>();
  if (!raw || !raw.trim()) return keys;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new LinkedAccountTokenEncryptionError(`${KEYS_SETTING} is not valid JSON`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || Object.keys(parsed).length === 0) {
    throw new LinkedAccountTokenEncryptionError(
      `${KEYS_SETTING} must be a non-empty JSON object mapping version to base64 key, e.g. {"1": "<base64 key>"}`
    );
  }
  for (const [versionText, value] of Object.entries(parsed as Record<string, unknown>)) {
    if (!/^\d+$/.test(versionText.trim())) {
      throw new LinkedAccountTokenEncryptionError(`key-version ${JSON.stringify(versionText)} is not an integer`);
    }
    const version = Number.parseInt(versionText, 10);
    if (version < 1) {
      throw new LinkedAccountTokenEncryptionError(`key-version ${version} is invalid; versions must be >= 1`);
    }
    if (typeof value !== 'string') {
      throw new LinkedAccountTokenEncryptionError(`master key for version ${version} must be a base64 string`);
    }
    keys.set(version, decodeMasterKey(value, version));
  }
  return keys;
}

/**
 * Resolve the key-version new tokens are sealed under.
 *
 * @param keys The parsed key map; must be non-empty.
 * @param env The environment to read the configured active version from.
 * @returns The configured active version, or the highest version present when none is configured.
 * @throws LinkedAccountTokenEncryptionError If the configured version is not an integer or has no key.
 */
function activeKeyVersion(keys: Map<number, Buffer>, env: TokenCryptoEnv): number {
  const configured = env[ACTIVE_VERSION_SETTING]?.trim();
  if (!configured) return Math.max(...keys.keys());
  if (!/^\d+$/.test(configured)) {
    throw new LinkedAccountTokenEncryptionError(`${ACTIVE_VERSION_SETTING} is not an integer`);
  }
  const version = Number.parseInt(configured, 10);
  if (!keys.has(version)) {
    throw new LinkedAccountTokenEncryptionError(`active key-version ${version} has no configured master key`);
  }
  return version;
}

/**
 * Whether token encryption is usable: at least one master key is configured and the map parses.
 *
 * @param env The environment to read from.
 * @returns `false` when no key is configured or the configuration is malformed.
 */
export function tokenEncryptionConfigured(env: TokenCryptoEnv = process.env): boolean {
  try {
    const keys = loadKeyMap(env);
    if (keys.size === 0) return false;
    activeKeyVersion(keys, env);
    return true;
  } catch {
    return false;
  }
}

/** The additional authenticated data binding a blob to this vault and key-version. */
function aad(version: number): Buffer {
  return Buffer.from(`OLAT:v${version}`, 'ascii');
}

/**
 * AES-256-GCM encrypt, returning `ciphertext || tag` (the layout Python's `AESGCM.encrypt` emits).
 *
 * @param key The 32-byte key.
 * @param nonce The 12-byte nonce.
 * @param plaintext The bytes to encrypt.
 * @param associated The additional authenticated data.
 * @returns The ciphertext followed by the 16-byte tag.
 */
function gcmEncrypt(key: Buffer, nonce: Buffer, plaintext: Buffer, associated: Buffer): Buffer {
  const cipher = createCipheriv(ALGORITHM, key, nonce);
  cipher.setAAD(associated);
  return Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]);
}

/**
 * AES-256-GCM decrypt of `ciphertext || tag`.
 *
 * @param key The 32-byte key.
 * @param nonce The 12-byte nonce.
 * @param sealed The ciphertext followed by the 16-byte tag.
 * @param associated The additional authenticated data.
 * @returns The plaintext bytes.
 * @throws Error If authentication fails (tampered data, wrong key or wrong AAD).
 */
function gcmDecrypt(key: Buffer, nonce: Buffer, sealed: Buffer, associated: Buffer): Buffer {
  const decipher = createDecipheriv(ALGORITHM, key, nonce, { authTagLength: TAG_LEN });
  decipher.setAAD(associated);
  decipher.setAuthTag(sealed.subarray(sealed.length - TAG_LEN));
  return Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - TAG_LEN)), decipher.final()]);
}

/**
 * Whether a stored column value is in the sealed `enc:v1:` form.
 *
 * @param value The raw column value.
 * @returns `true` for a sealed value; `false` for null, an empty string or legacy plaintext.
 */
export function isSealed(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith(SEALED_PREFIX);
}

/**
 * Seal a plaintext token into the string stored in a token column.
 *
 * @param token The plaintext OAuth token or personal access token; must be a non-empty string.
 * @param env The environment to read key material from.
 * @returns The sealed `enc:v1:<key_version>:<base64>` value to store.
 * @throws LinkedAccountTokenEncryptionError If encryption is not configured, the key map is
 *   malformed, or `token` is empty. The caller must not fall back to storing the plaintext.
 */
export function sealToken(token: string, env: TokenCryptoEnv = process.env): string {
  if (typeof token !== 'string' || token.length === 0) {
    throw new LinkedAccountTokenEncryptionError('token must be a non-empty string');
  }
  const keys = loadKeyMap(env);
  if (keys.size === 0) {
    throw new LinkedAccountTokenEncryptionError(
      `linked-account token encryption is not configured; set ${KEYS_SETTING} before storing a token`
    );
  }
  const version = activeKeyVersion(keys, env);
  const associated = aad(version);

  const dek = randomBytes(KEY_LEN);
  const payloadNonce = randomBytes(NONCE_LEN);
  const ciphertext = gcmEncrypt(dek, payloadNonce, Buffer.from(JSON.stringify({ token }), 'utf8'), associated);
  const wrapNonce = randomBytes(NONCE_LEN);
  const wrappedDek = gcmEncrypt(keys.get(version) as Buffer, wrapNonce, dek, associated);

  const blob = Buffer.concat([MAGIC, Buffer.from([FORMAT_VERSION]), wrapNonce, wrappedDek, payloadNonce, ciphertext]);
  return `${SEALED_PREFIX}${version}:${blob.toString('base64')}`;
}

/**
 * Seal a token for a path that must keep working when encryption is not configured.
 *
 * OAuth sign-in and account linking do not need the provider token to succeed, so when the token
 * cannot be sealed it is simply **not stored** — never written in plaintext.
 *
 * @param token The plaintext token, or null / empty when the provider issued none.
 * @param env The environment to read key material from.
 * @returns The sealed value, or `null` when there is no token or it cannot be sealed.
 */
export function sealTokenOrNull(token: string | null | undefined, env: TokenCryptoEnv = process.env): string | null {
  if (typeof token !== 'string' || token.length === 0) return null;
  try {
    return sealToken(token, env);
  } catch (error) {
    console.warn(
      `Linked-account token not stored: ${error instanceof Error ? error.message : 'encryption unavailable'}`
    );
    return null;
  }
}

/**
 * Return the plaintext token a stored column value represents.
 *
 * @param value The raw column value: sealed, legacy plaintext, empty or null.
 * @param env The environment to read key material from.
 * @returns The plaintext token; `null` when there is no token or a sealed value cannot be opened
 *   (encryption not configured, no key for its version, tampered or malformed). A legacy plaintext
 *   value is returned unchanged. The ciphertext itself is never returned.
 */
export function unsealToken(value: unknown, env: TokenCryptoEnv = process.env): string | null {
  if (typeof value !== 'string' || value.trim() === '') return null;
  if (!isSealed(value)) return value;

  const rest = value.slice(SEALED_PREFIX.length);
  const separator = rest.indexOf(':');
  const versionText = separator === -1 ? '' : rest.slice(0, separator);
  const body = rest.slice(separator + 1);
  if (!/^\d+$/.test(versionText) || !/^[A-Za-z0-9+/]+={0,2}$/.test(body)) {
    console.warn('Stored linked-account token is malformed; treating it as absent');
    return null;
  }
  const version = Number.parseInt(versionText, 10);

  try {
    const master = loadKeyMap(env).get(version);
    const blob = Buffer.from(body, 'base64');
    if (
      !master ||
      blob.length < MIN_BLOB_LEN ||
      !blob.subarray(0, MAGIC.length).equals(MAGIC) ||
      blob[MAGIC.length] !== FORMAT_VERSION
    ) {
      throw new Error('unusable envelope');
    }
    let offset = HEADER_LEN;
    const wrapNonce = blob.subarray(offset, (offset += NONCE_LEN));
    const wrappedDek = blob.subarray(offset, (offset += WRAPPED_DEK_LEN));
    const payloadNonce = blob.subarray(offset, (offset += NONCE_LEN));
    const associated = aad(version);
    const dek = gcmDecrypt(master, wrapNonce, wrappedDek, associated);
    const payload: unknown = JSON.parse(gcmDecrypt(dek, payloadNonce, blob.subarray(offset), associated).toString('utf8'));
    const token = (payload as { token?: unknown } | null)?.token;
    return typeof token === 'string' && token.length > 0 ? token : null;
  } catch {
    // Missing key, tampered / foreign blob or corrupt plaintext. The message stays secret-free.
    console.warn(`Failed to decrypt a linked-account token (key_version=${version}); treating it as absent`);
    return null;
  }
}
