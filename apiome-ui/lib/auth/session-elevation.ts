/**
 * The one reader of a session's two-factor elevation (BAA-2.3, apiome #6566; decision D8 of
 * `private-suite/docs/BETTER_AUTH_ALIGNMENT.md`).
 *
 * The app exposes two booleans that are easy to conflate:
 *
 * - `session.user.twoFactorEnabled` — the **account** completed TOTP enrolment (a profile fact);
 * - `session.twoFactorElevated` — **this session** cleared a second factor at issuance (an
 *   authorization fact).
 *
 * Access decisions and the `two_factor_elevated` claim of the service bearer (`lib/rest-auth.ts`)
 * read only the second. Anything that is not the boolean `true` is not elevation, so a session that
 * predates the marker, or a value that arrived as the string `"true"`, reads as a working,
 * non-elevated session rather than as an error or a pass.
 *
 * Pure — no session read, no environment, no I/O — so the same predicate runs in a route handler,
 * in a client component and in a test, and so the studio can import it without pulling the server
 * session module (which reaches for `next/headers`) into a browser bundle.
 */

/**
 * Read the elevation marker off a session.
 *
 * @param session The app session, or `null`/`undefined` when there is none.
 * @returns Whether the session positively asserts that it cleared a second factor.
 */
export function isSessionElevated(
  session: { twoFactorElevated?: unknown } | null | undefined
): boolean {
  return session?.twoFactorElevated === true;
}
