/**
 * Signed super-admin session tokens (OLO-8.1, #4967).
 *
 * The `/admin` portal previously gated on an *unsigned* cookie
 * (`base64("admin:" + Date.now())`) that anyone could hand-forge. Because the
 * portal is where OAuth **client secrets** are edited, that is unacceptable.
 *
 * This module replaces it with an HMAC-SHA256-signed token carrying an
 * issued-at (`iat`) and expiry (`exp`). The signature is verified with a
 * constant-time comparison and the expiry is enforced on every read, so a
 * cookie that was not minted by this server (or has expired) is rejected.
 *
 * Signing key resolution, in order:
 *   1. `ADMIN_SESSION_SECRET` — the dedicated, recommended secret.
 *   2. A value derived from `ADMIN_PASSWORD` — the admin login already requires
 *      this secret, so deployments that have not yet set a dedicated secret keep
 *      working (rotating the password also invalidates outstanding sessions).
 *
 * With neither configured there is no key, so sessions can be neither minted nor
 * verified: the portal fails closed rather than falling back to an unsigned token.
 */
import { createHmac, timingSafeEqual } from 'crypto';

/** Session lifetime: 8 hours, matching the historical admin cookie timeout. */
export const ADMIN_SESSION_MAX_AGE_MS = 8 * 60 * 60 * 1000;

/** Payload version, so the format can evolve without silently accepting old shapes. */
const ADMIN_SESSION_VERSION = 1;

/** Fixed subject claim; the admin portal has exactly one principal. */
const ADMIN_SESSION_SUBJECT = 'admin';

/** Shape of the JSON payload carried (base64url-encoded) in the token. */
interface AdminSessionPayload {
  /** Payload format version. */
  v: number;
  /** Subject — always {@link ADMIN_SESSION_SUBJECT}. */
  sub: string;
  /** Issued-at, epoch milliseconds. */
  iat: number;
  /** Expiry, epoch milliseconds. */
  exp: number;
}

/**
 * Resolve the HMAC signing key, or `null` when no secret is configured.
 *
 * Prefers the dedicated `ADMIN_SESSION_SECRET`; otherwise derives a stable key
 * from `ADMIN_PASSWORD` so existing deployments keep working without a new env
 * var. Returns `null` when neither is set, which makes the portal fail closed.
 *
 * @returns The signing key string, or `null` if none is available.
 */
function resolveSigningKey(): string | null {
  const dedicated = process.env.ADMIN_SESSION_SECRET?.trim();
  if (dedicated) {
    return dedicated;
  }

  const password = process.env.ADMIN_PASSWORD?.trim();
  if (password) {
    // Namespace the derived key so it can never collide with a raw password
    // used elsewhere, and so its purpose is self-documenting.
    return `apiome-admin-session:${password}`;
  }

  return null;
}

/** Base64url-encode a UTF-8 string (no padding), for URL/cookie-safe tokens. */
function base64UrlEncode(input: string): string {
  return Buffer.from(input, 'utf8').toString('base64url');
}

/** Compute the base64url HMAC-SHA256 signature of `payload` under `key`. */
function sign(payload: string, key: string): string {
  return createHmac('sha256', key).update(payload).digest('base64url');
}

/**
 * Compare two signatures in constant time, guarding against length mismatches
 * (which `timingSafeEqual` throws on) and non-ASCII input.
 *
 * @param a First signature.
 * @param b Second signature.
 * @returns Whether the signatures are byte-for-byte equal.
 */
function signaturesMatch(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) {
    return false;
  }
  return timingSafeEqual(bufA, bufB);
}

/**
 * Mint a signed admin session token valid for {@link ADMIN_SESSION_MAX_AGE_MS}.
 *
 * @param now Current time in epoch milliseconds (injectable for tests).
 * @returns The `"<payload>.<signature>"` token string.
 * @throws If no signing secret is configured (`ADMIN_SESSION_SECRET` /
 *   `ADMIN_PASSWORD`), so a caller can never issue an unsigned session.
 */
export function createAdminSessionToken(now: number = Date.now()): string {
  const key = resolveSigningKey();
  if (!key) {
    throw new Error(
      'Cannot create admin session: set ADMIN_SESSION_SECRET or ADMIN_PASSWORD.'
    );
  }

  const payload: AdminSessionPayload = {
    v: ADMIN_SESSION_VERSION,
    sub: ADMIN_SESSION_SUBJECT,
    iat: now,
    exp: now + ADMIN_SESSION_MAX_AGE_MS,
  };

  const encoded = base64UrlEncode(JSON.stringify(payload));
  return `${encoded}.${sign(encoded, key)}`;
}

/**
 * Verify a signed admin session token: signature first, then expiry.
 *
 * @param token The raw cookie value, or `undefined`/`null` when absent.
 * @param now Current time in epoch milliseconds (injectable for tests).
 * @returns `true` only when the signature is valid, the payload is well-formed
 *   for the current version, and the token has not expired.
 */
export function verifyAdminSessionToken(
  token: string | undefined | null,
  now: number = Date.now()
): boolean {
  if (!token) {
    return false;
  }

  const key = resolveSigningKey();
  if (!key) {
    return false;
  }

  const dot = token.indexOf('.');
  if (dot <= 0 || dot === token.length - 1) {
    return false;
  }

  const encoded = token.slice(0, dot);
  const signature = token.slice(dot + 1);

  // Reject any tampered token before trusting a single byte of its payload.
  if (!signaturesMatch(signature, sign(encoded, key))) {
    return false;
  }

  let payload: AdminSessionPayload;
  try {
    payload = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8'));
  } catch {
    return false;
  }

  if (
    payload.v !== ADMIN_SESSION_VERSION ||
    payload.sub !== ADMIN_SESSION_SUBJECT ||
    typeof payload.exp !== 'number' ||
    typeof payload.iat !== 'number'
  ) {
    return false;
  }

  return payload.exp > now;
}
