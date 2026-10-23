/**
 * Jest stub for `@better-auth/sso` (EID-1.1, #5011).
 *
 * The package is ESM-only, like `better-auth`. The stub returns a marker plugin that keeps its
 * options, so a test can assert how `lib/auth/auth.ts` configured the plugin (`defaultSSO`,
 * `modelName`, `saml`, …) without loading the real package.
 */

export const sso = (options?: Record<string, unknown>): { id: string; options: Record<string, unknown> } => ({
  id: 'sso',
  options: options ?? {},
});
