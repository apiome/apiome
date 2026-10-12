/**
 * Stub for `better-auth/crypto`, which is ESM-only (ts-jest's CommonJS transform cannot require
 * it). `lib/auth/auth.ts` reaches it through `two-factor-oauth-challenge.ts` (TFA-1.1 #5655).
 *
 * Deterministic stand-ins, enough for a module to load and run. Suites that assert on signatures
 * or random identifiers `jest.mock('better-auth/crypto')` with their own, which takes precedence.
 */

/** A fixed-shape stand-in for Better Auth's `generateRandomString`. */
export const generateRandomString = (length: number): string => 'x'.repeat(length);

/** A stand-in for Better Auth's `makeSignature`; never a real signature. */
export const makeSignature = async (value: string, secret: string): Promise<string> =>
  `stub-signature(${value},${secret.length})`;

/** Plain equality stand-in for Better Auth's `constantTimeEqual`. */
export const constantTimeEqual = (a: string, b: string): boolean => a === b;
