/**
 * Read Better Auth signed cookies outside an endpoint context (OLO-9.15 #5015, shared by
 * OLO-9.51 #5071).
 *
 * Better Auth signs some cookies (`trust_device`, `two_factor`) as `<value>.<base64 HMAC>`. Server
 * actions and server components have no Better Auth endpoint context to call `getSignedCookie`
 * on, so this mirrors its check. Kept outside any `'use server'` module so it can export plain
 * functions.
 */

import { constantTimeEqual, makeSignature } from 'better-auth/crypto';

/**
 * Verify a Better Auth signed cookie and return the unsigned payload.
 *
 * Mirrors `better-call`'s `getSignedCookie` signature check.
 *
 * @param raw Cookie value from the jar (URI-decoded).
 * @param secret Better Auth signing secret.
 * @returns Unsigned payload, or `null` when missing/invalid.
 */
export async function unsignBetterAuthCookie(raw: string, secret: string): Promise<string | null> {
  const signatureStartPos = raw.lastIndexOf('.');
  if (signatureStartPos < 1) return null;
  const signedValue = raw.substring(0, signatureStartPos);
  const signature = raw.substring(signatureStartPos + 1);
  if (signature.length !== 44 || !signature.endsWith('=')) return null;
  const expected = await makeSignature(signedValue, secret);
  return constantTimeEqual(signature, expected) ? signedValue : null;
}

/**
 * Read the first cookie present among `names`.
 *
 * @param store A cookie store (Next.js `cookies()`).
 * @param names Candidate names, e.g. the plain and `__Secure-` variants.
 * @returns The raw value, or `null` when none is set.
 */
export function readFirstCookie(
  store: { get: (name: string) => { value: string } | undefined },
  names: readonly string[],
): string | null {
  for (const name of names) {
    const value = store.get(name)?.value;
    if (value) return value;
  }
  return null;
}
