/**
 * Jest stub for `@better-auth/sso/client` (EID-1.1, #5011): a marker client plugin, so tests that
 * transitively import `lib/auth/auth-client.ts` load without the ESM-only package.
 */

export const ssoClient = (): { id: string } => ({ id: 'sso-client' });
