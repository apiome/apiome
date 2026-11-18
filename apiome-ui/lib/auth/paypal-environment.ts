/**
 * PayPal environment config — engine-neutral core (OLO-9.45, #5058).
 *
 * Pure, framework-free pieces of Log in with PayPal: the provider slug, the environment selector
 * and the hosts it picks — the OIDC issuer that drives discovery
 * (`<issuer>/.well-known/openid-configuration`) and the Identity API userinfo resource. Kept free
 * of better-auth imports so the Better Auth generic-OIDC wiring (`better-auth-oauth-providers.ts`)
 * and the tests can share one implementation with no framework coupling.
 *
 * `PAYPAL_ENVIRONMENT` is an **optional** extra. Unset (or anything but `sandbox`) means the live
 * PayPal hosts; `sandbox` selects PayPal's sandbox hosts, where a sandbox app's credentials and
 * sandbox test accounts sign in. The value is trimmed and case-insensitive. Unlike Better Auth's
 * `paypal()` helper (which defaults to sandbox), apiome defaults to live: a production deployment
 * must never quietly sign people in against test accounts.
 */

/**
 * The provider slug — the value stored in `external_auth_providers.provider` (the OLO-2.2
 * vocabulary) AND the Better Auth generic-OIDC `providerId`. Never rename: persisted identities and
 * the account-resolution gates match on it.
 */
export const PAYPAL_PROVIDER_ID = 'paypal';

/** The two PayPal environments an app's credentials can belong to. */
export type PaypalEnvironment = 'live' | 'sandbox';

/** The environment used when `PAYPAL_ENVIRONMENT` is unset: PayPal's production hosts. */
export const DEFAULT_PAYPAL_ENVIRONMENT: PaypalEnvironment = 'live';

/** OIDC issuer per environment — the host serving `/.well-known/openid-configuration`. */
const PAYPAL_ISSUERS: Readonly<Record<PaypalEnvironment, string>> = {
  live: 'https://www.paypal.com',
  sandbox: 'https://www.sandbox.paypal.com',
};

/** Identity API userinfo resource per environment (the one Better Auth's `paypal()` reads). */
const PAYPAL_USERINFO_URLS: Readonly<Record<PaypalEnvironment, string>> = {
  live: 'https://api-m.paypal.com/v1/identity/oauth2/userinfo?schema=paypalv1.1',
  sandbox: 'https://api-m.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=paypalv1.1',
};

/**
 * The PayPal environment the configured app belongs to.
 *
 * Read from `PAYPAL_ENVIRONMENT`, trimmed and lower-cased: `sandbox` selects the sandbox hosts;
 * unset, blank, `live` or any other value yields {@link DEFAULT_PAYPAL_ENVIRONMENT} (fail-safe to
 * production rather than to test accounts).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns `'sandbox'` or `'live'`; never anything else.
 */
export function paypalEnvironment(
  env: Record<string, string | undefined> = process.env
): PaypalEnvironment {
  const raw = env.PAYPAL_ENVIRONMENT;
  const normalized = typeof raw === 'string' ? raw.trim().toLowerCase() : '';
  return normalized === 'sandbox' ? 'sandbox' : DEFAULT_PAYPAL_ENVIRONMENT;
}

/**
 * URL of the PayPal OIDC discovery document for the configured environment.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The absolute `/.well-known/openid-configuration` URL.
 */
export function paypalDiscoveryUrl(env: Record<string, string | undefined> = process.env): string {
  return `${PAYPAL_ISSUERS[paypalEnvironment(env)]}/.well-known/openid-configuration`;
}

/**
 * URL of the PayPal Identity API userinfo resource for the configured environment, asked for in
 * the `paypalv1.1` schema (the profile, the email and its verified state).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The absolute userinfo URL, query string included.
 */
export function paypalUserInfoUrl(env: Record<string, string | undefined> = process.env): string {
  return PAYPAL_USERINFO_URLS[paypalEnvironment(env)];
}
