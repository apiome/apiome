/**
 * Salesforce issuer config — engine-neutral core (OLO-9.20, #5033).
 *
 * Pure, framework-free pieces of Salesforce sign-in: the provider slug, the OIDC issuer base URL
 * that drives discovery (`<issuer>/.well-known/openid-configuration`) and the userinfo resource
 * under the same issuer. Kept free of better-auth imports so the Better Auth generic-OIDC wiring
 * (`better-auth-oauth-providers.ts`) and the tests can share one implementation with no framework
 * coupling.
 *
 * Unlike Okta (`okta-issuer.ts`), the issuer is **optional**: every production org answers on
 * `https://login.salesforce.com`. `SALESFORCE_ISSUER` is set only to pin sign-in to one org's
 * My Domain (`https://acme.my.salesforce.com`) or to a sandbox (`https://test.salesforce.com`).
 * It is read the way `OKTA_ISSUER` is — trimmed, blank counts as unset, one trailing slash
 * stripped.
 */

/**
 * The provider slug — the value stored in `external_auth_providers.provider` (the OLO-2.2
 * vocabulary) AND the Better Auth generic-OIDC `providerId`. Never rename: persisted identities and
 * the account-resolution gates match on it.
 */
export const SALESFORCE_PROVIDER_ID = 'salesforce';

/** The issuer used when `SALESFORCE_ISSUER` is unset: Salesforce's production login host. */
export const DEFAULT_SALESFORCE_ISSUER_BASE_URL = 'https://login.salesforce.com';

/**
 * Read a trimmed env string, or null when unset/blank.
 *
 * @param env Environment map to read.
 * @param key Env var name.
 * @returns The trimmed value, or null when unset or blank.
 */
function readEnvString(env: Record<string, string | undefined>, key: string): string | null {
  const raw = env[key];
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Base URL of the Salesforce OIDC issuer the discovery document is fetched from.
 *
 * Read from `SALESFORCE_ISSUER` (e.g. `https://acme.my.salesforce.com`). Blank/whitespace counts
 * as unset and yields {@link DEFAULT_SALESFORCE_ISSUER_BASE_URL}; a trailing slash is stripped so
 * discovery path joining is stable.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The issuer base URL without a trailing slash; never empty.
 */
export function salesforceIssuerBaseUrl(
  env: Record<string, string | undefined> = process.env
): string {
  const raw = readEnvString(env, 'SALESFORCE_ISSUER') ?? DEFAULT_SALESFORCE_ISSUER_BASE_URL;
  return raw.endsWith('/') ? raw.slice(0, -1) : raw;
}

/**
 * URL of the Salesforce OIDC userinfo resource for the configured issuer
 * (`<issuer>/services/oauth2/userinfo`), read when the id token carries no email claim.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The absolute userinfo URL.
 */
export function salesforceUserInfoUrl(
  env: Record<string, string | undefined> = process.env
): string {
  return `${salesforceIssuerBaseUrl(env)}/services/oauth2/userinfo`;
}
