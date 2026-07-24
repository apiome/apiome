/**
 * Dependency-free TOTP generator for the OLO-10.13 2FA journey (#5008).
 *
 * The 2FA legs drive Better Auth's `twoFactor` HTTP endpoints directly (there is no 2FA UX yet — the
 * plugin is foundation-only, #5005). Enrolling returns an `otpauth://` URI whose `secret` is the
 * base32-encoded shared secret; to prove a login-with-code path the test must compute the current TOTP
 * from that secret. Better Auth's TOTP defaults are the RFC 6238 standard — HMAC-SHA1, 6 digits, 30s
 * period — so a small node-`crypto` implementation matches its verifier exactly, keeping this suite as
 * dependency-free as the mock OAuth server.
 */
import { createHmac } from 'node:crypto';

/** Better Auth twoFactor TOTP defaults (`two-factor/totp`): SHA1, 6 digits, 30-second step. */
const TOTP_DIGITS = 6;
const TOTP_PERIOD_SECONDS = 30;

/**
 * Extract the base32 shared secret from an `otpauth://totp/...` enrollment URI.
 *
 * @param totpUri The URI returned by `POST /two-factor/enable`.
 * @returns The `secret` query parameter (base32, no padding).
 * @throws Error when the URI carries no `secret`.
 */
export function parseTotpSecret(totpUri: string): string {
  const secret = new URL(totpUri).searchParams.get('secret');
  if (!secret) {
    throw new Error(`otpauth URI has no secret: ${totpUri}`);
  }
  return secret;
}

/** RFC 4648 base32 alphabet. */
const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/**
 * Decode an RFC 4648 base32 string (case-insensitive, padding optional) to raw bytes.
 *
 * @param input The base32 string (e.g. an `otpauth` `secret`).
 * @returns The decoded bytes.
 */
function base32Decode(input: string): Buffer {
  const clean = input.replace(/=+$/, '').toUpperCase();
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const char of clean) {
    const index = BASE32_ALPHABET.indexOf(char);
    if (index === -1) {
      throw new Error(`invalid base32 character: ${char}`);
    }
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      out.push((value >>> bits) & 0xff);
    }
  }
  return Buffer.from(out);
}

/**
 * Compute the TOTP code for a base32 secret at a given time (RFC 6238, HMAC-SHA1).
 *
 * @param secretBase32 The base32 shared secret from the enrollment URI.
 * @param atMs The instant to compute the code for; defaults to now.
 * @returns The zero-padded 6-digit TOTP code.
 */
export function generateTotp(secretBase32: string, atMs: number = Date.now()): string {
  const key = base32Decode(secretBase32);
  const counter = Math.floor(atMs / 1000 / TOTP_PERIOD_SECONDS);

  // 8-byte big-endian counter.
  const counterBuf = Buffer.alloc(8);
  counterBuf.writeBigUInt64BE(BigInt(counter));

  const digest = createHmac('sha1', key).update(counterBuf).digest();
  // Dynamic truncation (RFC 4226 §5.3).
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] & 0xff) << 16) |
    ((digest[offset + 2] & 0xff) << 8) |
    (digest[offset + 3] & 0xff);
  return (binary % 10 ** TOTP_DIGITS).toString().padStart(TOTP_DIGITS, '0');
}
