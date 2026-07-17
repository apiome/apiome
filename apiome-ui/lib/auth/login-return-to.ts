/**
 * Session-expiry return-to (OLO-3.4, #4202).
 *
 * When a protected shell notices the session is gone (expired, signed out in
 * another tab, revoked), it redirects to the login page. This helper builds
 * that redirect so the location the user was on survives the round trip: the
 * login page forwards it to NextAuth as `callbackUrl`, and the post-login
 * routing rules (OLO-3.3) land the user back where they were.
 *
 * Only same-origin relative paths are ever attached — the current location is
 * read from the router, but the value is still checked with
 * {@link isSafeRelativeCallbackPath} so a crafted path can never smuggle a
 * cross-origin target into the login redirect. The login page re-validates
 * against the full allowlist on the way back out.
 */
import { isSafeRelativeCallbackPath } from './cookie-options';

/** Path of the login page all expiry redirects target. */
export const LOGIN_PATH = '/login';

/**
 * Build the login redirect for an expired session, preserving the current
 * location as the post-login destination.
 *
 * @param pathname Current route pathname (e.g. `/ade/dashboard/projects`).
 * @param search Current query string, with or without the leading `?`.
 * @returns `/login?callbackUrl=<current location>`, or plain `/login` when the
 *   user is already on a login route or the path is unsafe to round-trip.
 */
export function buildLoginRedirect(pathname: string | null | undefined, search?: string | null): string {
  if (!pathname || pathname === LOGIN_PATH || pathname.startsWith(`${LOGIN_PATH}/`)) {
    return LOGIN_PATH;
  }

  const query = search ? (search.startsWith('?') ? search : `?${search}`) : '';
  const returnTo = `${pathname}${query}`;
  if (!isSafeRelativeCallbackPath(returnTo)) {
    return LOGIN_PATH;
  }

  return `${LOGIN_PATH}?callbackUrl=${encodeURIComponent(returnTo)}`;
}
