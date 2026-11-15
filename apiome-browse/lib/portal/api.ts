/**
 * The apiome-rest portal-auth calls Browse makes — PCX-1.1 (#5889).
 *
 * Wire types mirror `apiome-rest/src/app/portal_auth.py` (snake_case, as they arrive). Every call
 * takes the REST root (`…/v1`) and a `fetch` so the module stays framework-free and unit-testable.
 *
 * Where each call runs matters:
 *
 * - {@link requestMagicLink} runs **in the reader's browser** against the public REST URL, so the
 *   per-address rate limit sees the reader's own address rather than the Browse server's.
 * - {@link exchangeToken}, {@link fetchReader} and {@link signOutReader} run **on the Browse server**,
 *   because the session token must only ever live in an `HttpOnly` cookie.
 */

import { readerAuthHeader, refusalFromCode, type SignInRefusal } from './session';

/** The signed-in reader (`GET …/auth/me`). */
export interface ReaderProfile {
  user_id: string;
  email: string;
  name?: string | null;
  tenant_slug: string;
  tenant_name?: string | null;
  membership_status: 'invited' | 'active' | 'revoked';
  session_expires_at: string;
}

/** A new session (`POST …/auth/exchange`). */
export interface ReaderSessionGrant {
  session_token: string;
  expires_at: string;
  return_to?: string | null;
  reader: ReaderProfile;
}

/** The outcome of asking for a sign-in link. */
export type MagicLinkOutcome =
  | { ok: true }
  | { ok: false; kind: 'rate-limited'; retryAfterSeconds: number }
  | { ok: false; kind: 'invalid'; message: string }
  | { ok: false; kind: 'unavailable' };

/** The outcome of an exchange. */
export type ExchangeOutcome = { ok: true; grant: ReaderSessionGrant } | { ok: false; reason: SignInRefusal };

type Fetch = typeof fetch;

/**
 * The portal-auth root for a tenant.
 *
 * @param restBase - The REST root ending in `/v1`.
 * @param tenantSlug - The portal.
 * @returns `<restBase>/portal/<slug>/auth`.
 */
export function portalAuthUrl(restBase: string, tenantSlug: string): string {
  return `${restBase.replace(/\/+$/, '')}/portal/${encodeURIComponent(tenantSlug)}/auth`;
}

/**
 * Read `detail.code` and `detail.message` from a refusal body.
 *
 * @param response - A non-OK response.
 * @returns The code and message, each null when absent.
 */
async function readRefusal(response: Response): Promise<{ code: string | null; message: string | null }> {
  try {
    const body = (await response.json()) as { detail?: { code?: unknown; message?: unknown } | unknown };
    const detail = body.detail;
    if (detail && typeof detail === 'object') {
      const { code, message } = detail as { code?: unknown; message?: unknown };
      return {
        code: typeof code === 'string' ? code : null,
        message: typeof message === 'string' ? message : null,
      };
    }
  } catch {
    // An unreadable body is the same as one without a code.
  }
  return { code: null, message: null };
}

/**
 * Ask apiome-rest to mail a sign-in link. Runs in the browser.
 *
 * @param restBase - The public REST root.
 * @param tenantSlug - The portal.
 * @param email - The address as typed.
 * @param returnTo - Where to land after signing in.
 * @param fetchImpl - `fetch` (injectable for tests).
 * @returns `ok` for the `202` every well-formed request gets; otherwise why not.
 */
export async function requestMagicLink(
  restBase: string,
  tenantSlug: string,
  email: string,
  returnTo: string | null,
  fetchImpl: Fetch = fetch,
): Promise<MagicLinkOutcome> {
  let response: Response;
  try {
    response = await fetchImpl(`${portalAuthUrl(restBase, tenantSlug)}/magic-link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, ...(returnTo ? { return_to: returnTo } : {}) }),
    });
  } catch {
    return { ok: false, kind: 'unavailable' };
  }
  if (response.status === 202) return { ok: true };
  if (response.status === 429) {
    const retry = Number.parseInt(response.headers.get('Retry-After') ?? '', 10);
    return { ok: false, kind: 'rate-limited', retryAfterSeconds: Number.isFinite(retry) && retry > 0 ? retry : 60 };
  }
  if (response.status === 422) {
    const { message } = await readRefusal(response);
    return { ok: false, kind: 'invalid', message: message ?? 'Enter a valid email address.' };
  }
  return { ok: false, kind: 'unavailable' };
}

/**
 * Exchange a magic-link token for a session. Runs on the Browse server.
 *
 * @param restBase - The REST root reachable from the Browse server.
 * @param tenantSlug - The portal named in the link.
 * @param token - The token from the link.
 * @param userAgent - The reader's `User-Agent`, forwarded so REST can record the browser family.
 * @param fetchImpl - `fetch` (injectable for tests).
 * @returns The grant, or the reason the link was refused (a network fault reads as `invalid`).
 */
export async function exchangeToken(
  restBase: string,
  tenantSlug: string,
  token: string,
  userAgent: string | null,
  fetchImpl: Fetch = fetch,
): Promise<ExchangeOutcome> {
  try {
    const response = await fetchImpl(`${portalAuthUrl(restBase, tenantSlug)}/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(userAgent ? { 'User-Agent': userAgent } : {}) },
      body: JSON.stringify({ token }),
      cache: 'no-store',
    });
    if (response.ok) {
      return { ok: true, grant: (await response.json()) as ReaderSessionGrant };
    }
    const { code } = await readRefusal(response);
    return { ok: false, reason: refusalFromCode(code) };
  } catch {
    return { ok: false, reason: 'invalid' };
  }
}

/**
 * Read the signed-in reader. Runs on the Browse server.
 *
 * @param restBase - The REST root.
 * @param tenantSlug - The session's tenant.
 * @param token - The session token.
 * @param fetchImpl - `fetch` (injectable for tests).
 * @returns The reader, or null when the session is not live (or REST is unreachable).
 */
export async function fetchReader(
  restBase: string,
  tenantSlug: string,
  token: string,
  fetchImpl: Fetch = fetch,
): Promise<ReaderProfile | null> {
  try {
    const response = await fetchImpl(`${portalAuthUrl(restBase, tenantSlug)}/me`, {
      headers: readerAuthHeader(token),
      cache: 'no-store',
    });
    return response.ok ? ((await response.json()) as ReaderProfile) : null;
  } catch {
    return null;
  }
}

/**
 * Revoke a session. Runs on the Browse server; never throws, since signing out must always clear
 * the cookie whatever REST answers.
 *
 * @param restBase - The REST root.
 * @param tenantSlug - The session's tenant.
 * @param token - The session token.
 * @param fetchImpl - `fetch` (injectable for tests).
 */
export async function signOutReader(
  restBase: string,
  tenantSlug: string,
  token: string,
  fetchImpl: Fetch = fetch,
): Promise<void> {
  try {
    await fetchImpl(`${portalAuthUrl(restBase, tenantSlug)}/sign-out`, {
      method: 'POST',
      headers: readerAuthHeader(token),
      cache: 'no-store',
    });
  } catch {
    // The cookie is cleared regardless.
  }
}

/**
 * The REST root as the Browse **server** reaches it: the internal URL when one is configured, else
 * the public one, else the local default (the same precedence `lib/agentic/siteManifest` uses).
 *
 * @param env - The environment.
 * @returns The REST root ending in `/v1`.
 */
export function serverRestBase(env: Record<string, string | undefined>): string {
  return env.APIOME_REST_INTERNAL_BASE_URL || env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
}
