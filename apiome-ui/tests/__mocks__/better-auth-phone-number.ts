/**
 * Jest stub for `better-auth/plugins/phone-number` (OLO-9.51 #5071), which is ESM-only.
 *
 * The server instance registers the plugin; tests that load `lib/auth/auth.ts` only need the factory
 * to return a plugin-shaped marker. `better-auth-core.test.ts` asserts on the options it receives.
 */

export const phoneNumber = (
  options?: Record<string, unknown>,
): { id: string; options?: unknown } => ({
  id: 'phone-number',
  options,
});
