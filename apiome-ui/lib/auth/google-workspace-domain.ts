/**
 * Google Workspace-domain gate & issuer config — engine-neutral core (OLO-9.2, #4985).
 *
 * These are the *pure*, framework-free pieces of Google sign-in: the OIDC issuer base URL
 * (endpoint override for the OLO-7.4 e2e journey), the Workspace-domain (`hd`) restriction read,
 * and the `hd`-claim gate that is the **actual security boundary** for domain-restricted Google
 * sign-in. They were extracted here from `google-provider.ts` so both auth engines can share one
 * implementation:
 *
 *   - the NextAuth Google provider (`google-provider.ts`) — re-exports these and wires them into
 *     next-auth's built-in `GoogleProvider` profile callback;
 *   - the Better Auth generic-OIDC provider (`better-auth-oauth-providers.ts`, OLO-10.7) — calls the
 *     same gate from its `getUserInfo` hook before the account-resolution engine runs.
 *
 * Keeping the `hd` gate single-sourced means the two engines can never drift on the domain
 * restriction (the epic acceptance criterion: an out-of-domain account is rejected on Better Auth
 * exactly as on NextAuth). This module is deliberately free of both next-auth and better-auth
 * imports so either engine (and the mirror tests) can import it with no framework coupling — which
 * also lets the NextAuth Google provider be deleted at cutover (10.14) without touching the gate.
 */

/**
 * The provider slug — the value stored in `external_auth_providers.provider` (the OLO-2.2
 * vocabulary) AND the Better Auth generic-OIDC `providerId`. Never rename: persisted identities and
 * the account-resolution gates match on it.
 */
export const GOOGLE_PROVIDER_ID = 'google';

/** The real Google OIDC issuer host (production default for {@link googleIssuerBaseUrl}). */
export const DEFAULT_GOOGLE_ISSUER_BASE_URL = 'https://accounts.google.com';

/** The Google id-token claims the domain gate + resolution engine read (others pass through). */
export interface GoogleProfile extends Record<string, unknown> {
  /** Stable, immutable Google account id — the provider_user_id. */
  sub?: string;
  name?: string;
  email?: string;
  /** Google's own verified-email signal, read by `resolveOAuthEmailVerified` (OLO-2.5). */
  email_verified?: boolean;
  picture?: string;
  /**
   * "Hosted domain" — present only for Google Workspace accounts, carrying the account's Workspace
   * domain. Absent for personal `@gmail.com` accounts. The claim the domain gate checks.
   */
  hd?: string;
}

/**
 * Read a trimmed env string, or null when unset/blank — a local copy of the registry helper so this
 * module stays free of provider-registry (and thus of any framework) imports.
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
 * Base URL of the Google OIDC issuer the discovery document is fetched from. Overridable via
 * `GOOGLE_ISSUER` for the mocked-provider e2e journey (OLO-7.4); defaults to the real Google host.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The issuer base URL without a trailing slash.
 */
export function googleIssuerBaseUrl(
  env: Record<string, string | undefined> = process.env
): string {
  const raw = readEnvString(env, 'GOOGLE_ISSUER') ?? DEFAULT_GOOGLE_ISSUER_BASE_URL;
  return raw.endsWith('/') ? raw.slice(0, -1) : raw;
}

/**
 * The Workspace domain this deployment restricts Google sign-in to, or null when unrestricted.
 *
 * Read from `GOOGLE_WORKSPACE_DOMAIN` (blank/whitespace counts as unset, per {@link readEnvString}).
 * Also surfaced as an optional admin "extra" field overlaid onto the same env key (OLO-8.5).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The configured Workspace domain, or null when none is set.
 */
export function googleWorkspaceDomain(
  env: Record<string, string | undefined> = process.env
): string | null {
  return readEnvString(env, 'GOOGLE_WORKSPACE_DOMAIN');
}

/**
 * Whether a token's `hd` claim satisfies the configured Workspace domain, comparing
 * case-insensitively and ignoring surrounding whitespace (domains are case-insensitive).
 *
 * @param claim The raw `hd` claim from the id token (any type; only a matching string passes).
 * @param domain The configured Workspace domain (already known non-blank).
 * @returns True only when `claim` is a string equal to `domain` ignoring case/whitespace.
 */
export function hostedDomainMatches(claim: unknown, domain: string): boolean {
  return (
    typeof claim === 'string' &&
    claim.trim().toLowerCase() === domain.trim().toLowerCase()
  );
}

/**
 * Enforce the Workspace-domain gate: throw when a domain is configured and the profile's `hd`
 * claim does not match it. A no-op when no domain is configured (any Google account is allowed).
 *
 * Throwing before the account-resolution engine runs aborts the sign-in so a foreign-domain or
 * personal account never lands an identity — this is the real boundary the advisory `hd`
 * authorization parameter cannot guarantee on its own (per Google's OIDC docs the parameter is a
 * hint; a determined user can still complete the flow with a non-domain account).
 *
 * @param profile The raw Google id-token claims.
 * @param domain The configured Workspace domain, or null when unrestricted.
 * @throws Error when a domain is configured and `profile.hd` does not match it.
 */
export function assertGoogleHostedDomain(profile: GoogleProfile, domain: string | null): void {
  if (domain === null) return;
  if (!hostedDomainMatches(profile.hd, domain)) {
    throw new Error(
      `Google sign-in rejected: this account is not a member of the '${domain}' Google Workspace ` +
        `domain (hd claim: ${JSON.stringify(profile.hd ?? null)}).`
    );
  }
}
