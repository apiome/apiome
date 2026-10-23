/**
 * Jest stub for `jose` (EID-1.1, #5011).
 *
 * `jose` v6 is ESM-only, and `lib/auth/auth.ts` now reaches it through the SSO id-token check
 * (`sso-resolution.ts`). Suites that load the server instance get these inert stubs; a suite that
 * exercises id-token verification `jest.mock`s `jose` itself, which takes precedence.
 */

export const createRemoteJWKSet = (): (() => Promise<never>) => async () => {
  throw new Error('jose is stubbed in jest');
};

export const jwtVerify = async (): Promise<never> => {
  throw new Error('jose is stubbed in jest');
};

export type JWTPayload = Record<string, unknown>;
