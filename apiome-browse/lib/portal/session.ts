/**
 * Reader session helpers — PCX-1.1 (#5889).
 *
 * A **reader** signs in to one tenant's portal with a magic link. apiome-rest mints an opaque,
 * tenant-bound session token; Browse keeps it in an `HttpOnly; Secure; SameSite=Lax` cookie scoped
 * to `NEXT_PUBLIC_BASE_PATH` and forwards it to REST as `Authorization: Reader <token>`. The token is
 * never readable by page scripts and never shown to the reader.
 *
 * The cookie carries the tenant slug beside the token (`<slug>:<token>`) because every portal REST
 * route is addressed by tenant, and a session for one portal must not be sent to another.
 *
 * Framework-free, so it is unit-testable under the browse Vitest setup (node environment,
 * `lib/**` only). The pieces that touch `next/headers` live in `src/app/portal/readerSession.ts`.
 */

/** The cookie that holds the reader session. */
export const READER_SESSION_COOKIE = 'apiome_reader_session';

/** The `Authorization` scheme apiome-rest reads a reader session from. */
export const READER_SCHEME = 'Reader';

/** A tenant slug as apiome-rest accepts it in a portal route. */
const TENANT_SLUG = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;

/** The shape of a session token (`prs_` + URL-safe base64). */
const SESSION_TOKEN = /^prs_[A-Za-z0-9_-]{20,124}$/;

/** A parsed reader cookie. */
export interface ReaderCookie {
  /** The tenant the session is bound to. */
  tenantSlug: string;
  /** The opaque session token. */
  token: string;
}

/** The options a reader cookie is set with. */
export interface ReaderCookieOptions {
  httpOnly: true;
  secure: boolean;
  sameSite: 'lax';
  path: string;
  expires: Date;
}

/**
 * Whether a string is a tenant slug a portal route accepts.
 *
 * @param slug - The candidate slug.
 * @returns True for a lower-case slug of letters, digits and inner hyphens.
 */
export function isTenantSlug(slug: string | null | undefined): slug is string {
  return typeof slug === 'string' && TENANT_SLUG.test(slug);
}

/**
 * Serialise a session for the cookie.
 *
 * @param tenantSlug - The tenant the session is bound to.
 * @param token - The session token.
 * @returns `<slug>:<token>`.
 */
export function encodeReaderCookie(tenantSlug: string, token: string): string {
  return `${tenantSlug}:${token}`;
}

/**
 * Parse the cookie value, refusing anything that is not exactly what {@link encodeReaderCookie}
 * writes.
 *
 * @param value - The raw cookie value, if any.
 * @returns The tenant and token, or null.
 */
export function parseReaderCookie(value: string | null | undefined): ReaderCookie | null {
  if (!value) return null;
  const separator = value.indexOf(':');
  if (separator <= 0) return null;
  const tenantSlug = value.slice(0, separator);
  const token = value.slice(separator + 1);
  if (!isTenantSlug(tenantSlug) || !SESSION_TOKEN.test(token)) return null;
  return { tenantSlug, token };
}

/**
 * The cookie options for a reader session.
 *
 * @param basePath - `NEXT_PUBLIC_BASE_PATH` (empty when Browse is served at the root).
 * @param expires - When the session ends (from apiome-rest).
 * @param production - Whether to mark the cookie `Secure`. Local `http://localhost` development
 *   needs it off; every deployed environment has it on.
 * @returns `HttpOnly; SameSite=Lax`, scoped to the base path, expiring with the session.
 */
export function readerCookieOptions(
  basePath: string | undefined,
  expires: Date,
  production: boolean,
): ReaderCookieOptions {
  const path = basePath && basePath.startsWith('/') ? basePath.replace(/\/+$/, '') || '/' : '/';
  return { httpOnly: true, secure: production, sameSite: 'lax', path, expires };
}

/**
 * The header that carries a session to apiome-rest.
 *
 * @param token - The session token.
 * @returns `{ Authorization: 'Reader <token>' }`.
 */
export function readerAuthHeader(token: string): Record<string, string> {
  return { Authorization: `${READER_SCHEME} ${token}` };
}

/**
 * Accept a post-sign-in destination only when it stays inside Browse — the same rule apiome-rest
 * applies when it stores `return_to`, applied again before the redirect.
 *
 * @param raw - The requested path.
 * @param fallback - Where to go when it is missing or refused.
 * @returns A same-site path.
 */
export function safeReturnTo(raw: string | null | undefined, fallback: string): string {
  if (
    !raw ||
    raw.length > 1024 ||
    !raw.startsWith('/') ||
    raw.startsWith('//') ||
    raw.includes('\\') ||
    /[\u0000-\u001f\u007f]/.test(raw)
  ) {
    return fallback;
  }
  return raw;
}

/**
 * Whether a state-changing POST came from this site.
 *
 * The session and sign-out handlers change who the browser is signed in as, so a cross-site form
 * must not be able to post to them (login CSRF). Browsers send `Origin` on every POST; a request
 * without one is refused as well.
 *
 * @param origin - The request's `Origin` header.
 * @param requestUrl - The URL the request was made to.
 * @returns True when the origins match exactly.
 */
export function isSameOriginPost(origin: string | null, requestUrl: string): boolean {
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(requestUrl).origin;
  } catch {
    return false;
  }
}

/** Why a sign-in link could not be used. */
export type SignInRefusal = 'expired' | 'used' | 'invalid';

/**
 * Map an apiome-rest refusal code to the reason the error page names.
 *
 * @param code - The `detail.code` from the exchange response, if any.
 * @returns `expired`, `used`, or `invalid` for anything else.
 */
export function refusalFromCode(code: string | null | undefined): SignInRefusal {
  if (code === 'portal-token-expired') return 'expired';
  if (code === 'portal-token-used') return 'used';
  return 'invalid';
}

/**
 * Parse the `reason` query parameter of the error page.
 *
 * @param raw - The parameter.
 * @returns A known reason, defaulting to `invalid`.
 */
export function parseRefusal(raw: string | null | undefined): SignInRefusal {
  return raw === 'expired' || raw === 'used' ? raw : 'invalid';
}

/** What the error page says for each reason. */
export const REFUSAL_COPY: Record<SignInRefusal, { title: string; body: string }> = {
  expired: {
    title: 'This sign-in link has expired',
    body: 'Sign-in links work for 15 minutes. Ask for a new one and use it straight away.',
  },
  used: {
    title: 'This sign-in link has already been used',
    body: 'Each link signs you in once. If that was not you, ask for a new link — the old one cannot be used again.',
  },
  invalid: {
    title: 'This sign-in link is not valid',
    body: 'The link may be incomplete or meant for another portal. Ask for a new one.',
  },
};

/**
 * Build a Browse path with a query string.
 *
 * @param path - The path (without the base path; Next adds it).
 * @param params - Query parameters; empty and missing values are dropped.
 * @returns `path?query`, or just `path`.
 */
export function portalPath(path: string, params: Record<string, string | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value);
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}
