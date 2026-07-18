/**
 * Next.js server-startup hook (OLO-7.2, #4224).
 *
 * `register()` runs once when the server boots (dev and production alike), before any
 * request is served. It validates the sign-in provider env config so a partially-configured
 * provider (e.g. a client id without its secret) fails loud at startup with an actionable
 * message instead of degrading silently at first login. `AUTH_PROVIDER_VALIDATION=warn`
 * downgrades the failure to a logged warning that leaves the provider cleanly disabled.
 *
 * See `lib/auth/provider-registry.ts` (`validateProviderEnv`) and
 * `docs/AUTH_PROVIDER_SETUP.md`.
 */
export async function register(): Promise<void> {
  // Only the Node.js server reads provider secrets; skip the edge runtime so each issue is
  // reported once and the auth modules stay out of the edge bundle.
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  const { validateProviderEnv } = await import('../lib/auth/provider-registry');
  validateProviderEnv();
}
