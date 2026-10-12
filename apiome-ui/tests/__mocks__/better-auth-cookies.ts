/**
 * Stub for `better-auth/cookies`, which is ESM-only (ts-jest's CommonJS transform cannot require
 * it). `lib/auth/auth.ts` reaches it through `two-factor-oauth-challenge.ts` (TFA-1.1 #5655), so
 * every suite that imports the server instance would otherwise fail to parse.
 *
 * The functions do nothing: suites that assert on cookie handling `jest.mock('better-auth/cookies')`
 * with their own spies, which takes precedence over this mapping.
 */

/** No-op stand-in for Better Auth's `deleteSessionCookie`. */
export const deleteSessionCookie = (): void => undefined;

/** No-op stand-in for Better Auth's `expireCookie`. */
export const expireCookie = (): void => undefined;
