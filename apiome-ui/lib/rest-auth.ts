/**
 * The service bearer for server-side calls to apiome-rest — and, through the studio's re-export, to
 * `spire` (BAA-2.3, apiome #6566).
 *
 * **One implementation.** The private suite's `designer` re-exports this module
 * (`private-suite/designer/lib/rest-auth.ts`) rather than carrying a copy, the same way it imports
 * the Better Auth instance, the cookie resolver and the session readers (alignment record decisions
 * D1, D2 and D5). Before BAA-2.3 the two apps held diverged copies and the studio ran both — its
 * own in its BFF routes, this one inside the shared tenant switcher — so one origin minted two
 * different tokens from one session.
 *
 * The bearer is a **hand-minted HS256 JWT** (decision D6: Better Auth's JWT/bearer plugin was
 * deliberately not adopted, because apiome-rest and `spire` verify a shared HMAC secret). What it
 * carries is pinned in `private-suite/docs/contracts/suite-auth-token.contract.json`, which the
 * studio's and `spire`'s contract tests both read; adding, renaming or dropping a claim here is a
 * cross-service change, not a local edit.
 *
 * - **Secret:** `BETTER_AUTH_SECRET`, read through {@link resolveBetterAuthSecret} so this module can
 *   never disagree with the instance that issues the session. Verified by apiome-rest
 *   (`BETTER_AUTH_SECRET` → `JWT_SECRET`) and by `spire` (the same chain).
 * - **Claims:** the `AppSession` user — `user_id` / `email` / `name` / `current_tenant_id` — plus the
 *   session-level `twoFactorElevated` marker, signed as `two_factor_elevated`
 *   ({@link restSessionUser} folds it onto the user; see decision D8).
 * - **Lifetime:** one hour.
 */

import jwt from 'jsonwebtoken';

import { resolveBetterAuthSecret } from './auth/better-auth-session';
import { isSessionElevated } from './auth/session-elevation';

/**
 * The session facts the bearer is minted from.
 *
 * Field names are the **claim** names (snake_case), which is why the session-level elevation marker
 * is carried here as `two_factor_elevated` rather than the session object's camelCase
 * `twoFactorElevated`. Build one with {@link restSessionUser} instead of by hand, so the marker can
 * never be silently dropped on the way to the signer.
 */
export interface SessionUserForRest {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
  /**
   * Whether **this session** cleared a second factor at issuance (the app's
   * `session.twoFactorElevated`).
   *
   * Never the account's `twoFactorEnabled` — enrolment is a profile fact, elevation an authorization
   * fact (decision D8). Absent is treated as `false` by the signer and by every verifier, so a
   * session that never carried the marker is a working non-elevated session, not an error.
   */
  two_factor_elevated?: boolean;
}

/**
 * The parts of an `AppSession` this module reads.
 *
 * Declared structurally rather than importing `AppSession`, so nothing here depends on the session
 * *module* (which reaches for the database) — only on the shape it returns.
 */
export interface AppSessionForRest<TUser extends SessionUserForRest = SessionUserForRest> {
  /** The app-contract user: `user_id`, `email`, `name`, `current_tenant_id`. */
  user: TUser;
  /** True when this session cleared 2FA at issuance; absent on any session predating the marker. */
  twoFactorElevated?: boolean;
}

/**
 * Flatten an app session into the claim carrier {@link createRestAuthHeaders} signs.
 *
 * The 2FA marker lives on the *session*, not the user, while every REST call site holds only a user
 * — so it has to be folded in exactly once, here, at the point the session is still whole. Call this
 * immediately after reading the session; passing `session.user` straight to the signer mints a token
 * that silently claims `two_factor_elevated: false`.
 *
 * @param session The app session, already null-checked by the caller.
 * @returns The session user with the elevation marker resolved to a definite boolean; extra fields
 *   the caller carries (e.g. `is_tenant_admin`) are preserved.
 */
export function restSessionUser<TUser extends SessionUserForRest>(
  session: AppSessionForRest<TUser>
): TUser & { two_factor_elevated: boolean } {
  return { ...session.user, two_factor_elevated: isSessionElevated(session) };
}

/**
 * The shared secret the service bearer is signed with.
 *
 * Delegates to the Better Auth secret resolver (`BETTER_AUTH_SECRET`, blank counted as unset) so
 * the bearer is signed with exactly the value the session instance was configured with.
 *
 * @returns The signing secret, or `undefined` when it is unset — in which case no bearer is minted.
 */
export function getRestJwtSigningSecret(): string | undefined {
  return resolveBetterAuthSecret();
}

/**
 * The shared JWT signing secret for minting apiome-rest Bearer tokens.
 *
 * @deprecated Prefer {@link getRestJwtSigningSecret}; kept for existing call sites.
 * @returns The trimmed `BETTER_AUTH_SECRET`, or `undefined` when unset/blank.
 */
export function getJwtSigningSecret(): string | undefined {
  return getRestJwtSigningSecret();
}

/**
 * Normalize the principal id carried by a session user.
 *
 * Under the Better Auth contract `user_id` is always populated — it *is* Better Auth's `user.id`,
 * re-keyed by `toAppSessionUser()`. There is deliberately no fallback to a legacy `user.id`: a bare
 * `id` is not a principal, and a silent second path to the principal is how the two apps would come
 * to disagree about who is calling.
 *
 * @param user The session user, or `null`/`undefined` when there is no session.
 * @returns The trimmed principal id, or `undefined` when absent or blank.
 */
export function resolveSessionPrincipalId(
  user: SessionUserForRest | null | undefined
): string | undefined {
  const principalId = user?.user_id;
  if (!principalId) return undefined;
  const normalized = String(principalId).trim();
  return normalized.length > 0 ? normalized : undefined;
}

/** Bearer lifetime, as `jsonwebtoken` spells it; the contract file pins it as 3600 seconds. */
const REST_BEARER_LIFETIME = '1h';

/**
 * Create the headers for a server-side REST call, including the Bearer JWT.
 *
 * Fails **closed**: with no principal or no signing secret the call still goes out, but carries only
 * `Content-Type` — an unauthenticated request the REST tier rejects with a 401, rather than a token
 * asserting an identity this process could not establish.
 *
 * An optional claim whose value is `undefined` is not signed at all (JSON serialization drops it),
 * which is what the contract's "absent for a tenant-less user" means; `two_factor_elevated` is
 * always signed, as a definite boolean.
 *
 * @param user The session facts to sign, as returned by {@link restSessionUser}.
 * @returns `Content-Type`, plus `Authorization: Bearer <jwt>` when a token could be minted.
 */
export function createRestAuthHeaders(user: SessionUserForRest): Record<string, string> {
  const principalId = resolveSessionPrincipalId(user);
  if (!principalId) {
    return { 'Content-Type': 'application/json' };
  }
  const secret = getRestJwtSigningSecret();
  if (!secret) {
    return { 'Content-Type': 'application/json' };
  }
  const token = jwt.sign(
    {
      user_id: principalId,
      sub: principalId,
      email: user.email,
      name: user.name,
      current_tenant_id: user.current_tenant_id,
      two_factor_elevated: user.two_factor_elevated === true,
    },
    secret,
    { algorithm: 'HS256', expiresIn: REST_BEARER_LIFETIME }
  );
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

const DEFAULT_REST_API_BASE_URL = 'http://localhost:8000/v1';

function normalizeRestApiBaseUrl(url: string): string {
  return url.replace(/\/+$/, '');
}

/**
 * apiome-rest's base URL for server-side calls, resolved **at call time**.
 *
 * Prefers `REST_API_BASE_URL`, a runtime variable (so a container can point at `http://rest:8000/v1`
 * without a rebuild), and falls back to `NEXT_PUBLIC_REST_API_BASE_URL`, which Next.js inlines at
 * build time, for local `next dev` and older builds. Trailing slashes are stripped so callers can
 * always append `/path`.
 *
 * @returns The base URL, e.g. `http://rest:8000/v1`.
 */
export function getRestApiBaseUrl(): string {
  const runtime = process.env.REST_API_BASE_URL?.trim();
  if (runtime) return normalizeRestApiBaseUrl(runtime);
  const built = process.env.NEXT_PUBLIC_REST_API_BASE_URL?.trim();
  if (built) return normalizeRestApiBaseUrl(built);
  return DEFAULT_REST_API_BASE_URL;
}

/**
 * The build-time REST base URL, frozen when the module loads.
 *
 * Kept for the existing call sites; it ignores the runtime `REST_API_BASE_URL`, so new code and
 * anything that runs in a container should call {@link getRestApiBaseUrl} instead.
 */
export const REST_API_BASE_URL =
  process.env.NEXT_PUBLIC_REST_API_BASE_URL || DEFAULT_REST_API_BASE_URL;

function readFetchErrorCode(error: unknown): string | undefined {
  if (!error || typeof error !== 'object' || !('cause' in error)) return undefined;
  const cause = (error as { cause?: unknown }).cause;
  if (!cause || typeof cause !== 'object' || !('code' in cause)) return undefined;
  const code = (cause as { code?: unknown }).code;
  return typeof code === 'string' ? code : undefined;
}

/**
 * Server-side fetch to apiome-rest that names the target when the connection itself fails.
 *
 * A refused connection or an unresolvable host otherwise surfaces as a bare `fetch failed`, which
 * says nothing about which base URL this process was given; logging the method, URL and the
 * underlying code (`ECONNREFUSED`, `ENOTFOUND`) is what makes a wrong `REST_API_BASE_URL` findable.
 *
 * @param url The absolute REST URL.
 * @param init Request options, forwarded verbatim.
 * @returns The upstream response.
 * @throws Whatever `fetch` threw, after logging it.
 */
export async function fetchRestApi(url: string, init: RequestInit = {}): Promise<Response> {
  const method = init.method ?? 'GET';
  try {
    return await fetch(url, init);
  } catch (error) {
    const code = readFetchErrorCode(error);
    const codeSuffix = code ? ` (${code})` : '';
    console.error(`[rest-auth] REST fetch failed: ${method} ${url}${codeSuffix}`, error);
    throw error;
  }
}
