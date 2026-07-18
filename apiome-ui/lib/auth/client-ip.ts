/**
 * Best-effort client IP resolution for rate-limit keys (OLO-7.1, #4223).
 *
 * Next.js route handlers run behind the platform proxy, so the socket peer is the
 * proxy itself and the forwarded headers are the only per-client signal available.
 * The first `x-forwarded-for` hop (falling back to `x-real-ip`) is used — the same
 * convention the super-admin password form has always applied. When neither header
 * is present (e.g. a direct local connection) every caller shares the `'unknown'`
 * bucket, which degrades to a coarse global throttle rather than no throttle.
 *
 * Note: forwarded headers are client-suppliable when the app is exposed without a
 * trusted proxy, so these keys harden brute-force cost rather than provide a
 * security boundary; pair with per-account keys (as the auth surface does).
 */

/**
 * Header containers this helper accepts: a WHATWG `Headers` (route handlers) or a
 * plain header object (NextAuth's `authorize(credentials, req)` request shape).
 */
export type HeaderLookup =
  | { get(name: string): string | null }
  | Record<string, string | string[] | undefined>;

/** Read a single header value from either supported container shape. */
function readHeader(headers: HeaderLookup, name: string): string | null {
  if (typeof (headers as { get?: unknown }).get === 'function') {
    return (headers as { get(name: string): string | null }).get(name);
  }
  const value = (headers as Record<string, string | string[] | undefined>)[name];
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

/**
 * Resolve the caller's IP for use in a rate-limit key.
 *
 * @param headers Request headers (`Headers` instance or plain object; case-sensitive
 *   lower-case names are expected for the plain-object shape, which is how both
 *   Next.js and Node deliver them).
 * @returns The first `x-forwarded-for` hop, else `x-real-ip`, else `'unknown'`.
 */
export function resolveClientIp(headers: HeaderLookup | null | undefined): string {
  if (!headers) {
    return 'unknown';
  }
  const forwarded = readHeader(headers, 'x-forwarded-for');
  const firstHop = forwarded?.split(',')[0]?.trim();
  if (firstHop) {
    return firstHop;
  }
  const realIp = readHeader(headers, 'x-real-ip')?.trim();
  return realIp || 'unknown';
}
