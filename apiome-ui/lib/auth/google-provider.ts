/**
 * Google Workspace (google) NextAuth provider (OLO-9.2, #4985).
 *
 * Wraps next-auth v4's built-in `GoogleProvider` (OIDC authorization-code + PKCE against
 * `accounts.google.com`) rather than hand-rolling the OIDC config: Google's discovery document,
 * PKCE checks, and `sub`→id / `email`/`email_verified` claim mapping are exactly what the built-in
 * gives, and Google's id token natively carries `email_verified`, so the generic
 * `resolveOAuthEmailVerified` path (OLO-2.5) trusts a verified Google address with no userinfo
 * override — `google` only needs to join `AUTO_LINK_TRUSTED_PROVIDERS`.
 *
 * The one thing the built-in does not do is **Workspace-domain restriction**. When a deployment
 * sets `GOOGLE_WORKSPACE_DOMAIN`, this module:
 *
 *   1. adds the `hd` ("hosted domain") authorization parameter, so Google's account chooser only
 *      offers accounts in that Workspace domain, and
 *   2. **verifies the `hd` claim** in the profile callback and rejects any account whose `hd` does
 *      not match. Per Google's OIDC docs the `hd` *parameter* is advisory — a determined user can
 *      still complete the flow with a personal or foreign-domain account — so the claim check is
 *      the actual security boundary. Without a configured domain, any Google account may sign in.
 *
 * Trust boundary: this module maps the OIDC response onto a NextAuth user and enforces the domain
 * gate. Whether the email claim may be believed for auto-link is still decided later by
 * `resolveOAuthEmailVerified` (OLO-1.3/2.5) inside the shared signIn callback — never here.
 *
 * Server-only: imports the next-auth Google provider factory. Client code wanting provider
 * metadata should import `provider-registry.ts` (data) or `provider-brand.tsx` (icons) instead.
 */
import GoogleProvider from 'next-auth/providers/google';
import type { OAuthConfig } from 'next-auth/providers/oauth';
import { readEnvString } from './provider-registry';

/**
 * The provider slug — the NextAuth provider id AND the value stored in
 * `external_auth_providers.provider` (the OLO-2.2 vocabulary). Never rename: persisted identities
 * and the account-resolution gates match on it.
 */
export const GOOGLE_PROVIDER_ID = 'google';

/** The real Google OIDC issuer host (production default for {@link googleIssuerBaseUrl}). */
const DEFAULT_ISSUER_BASE_URL = 'https://accounts.google.com';

/** The Google id-token claims this module reads (all others pass through untouched). */
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
 * Base URL of the Google OIDC issuer the discovery document is fetched from. Overridable via
 * `GOOGLE_ISSUER` for the mocked-provider e2e journey (OLO-7.4); defaults to the real Google host.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The issuer base URL without a trailing slash.
 */
export function googleIssuerBaseUrl(
  env: Record<string, string | undefined> = process.env
): string {
  const raw = readEnvString(env, 'GOOGLE_ISSUER') ?? DEFAULT_ISSUER_BASE_URL;
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
 * Throwing inside the provider's profile callback aborts the sign-in before the account-resolution
 * engine runs, so a foreign-domain or personal account never lands an identity — this is the real
 * boundary the advisory `hd` authorization parameter cannot guarantee on its own.
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

/**
 * Map the raw Google id-token claims onto the NextAuth user shape, enforcing the domain gate first.
 *
 * `id` becomes `account.providerAccountId`, which the resolution engine persists as
 * `provider_user_id` — so it is the immutable `sub`. The raw claims themselves still reach the
 * signIn callback as `profile`, where `resolveOAuthEmailVerified` reads `email_verified` (OLO-2.5).
 *
 * @param profile The raw Google id-token claims.
 * @param domain The configured Workspace domain, or null when unrestricted.
 * @returns The NextAuth user: stable id, display name, email, and avatar.
 * @throws Error (via {@link assertGoogleHostedDomain}) when the domain gate rejects the account.
 */
export function googleProfile(profile: GoogleProfile, domain: string | null) {
  assertGoogleHostedDomain(profile, domain);
  return {
    id: (profile.sub ?? '') as string,
    name: profile.name ?? null,
    email: profile.email ?? null,
    image: profile.picture ?? null,
  };
}

/**
 * Build the Google OAuth provider config (OIDC authorization-code flow via the built-in factory).
 *
 * Adds the `hd` authorization parameter and the `hd`-claim profile gate when
 * `GOOGLE_WORKSPACE_DOMAIN` is set; otherwise behaves as the stock Google provider. Discovery is
 * pointed at `googleIssuerBaseUrl` so the e2e journey can substitute a mock issuer (OLO-7.4).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns A NextAuth OAuth provider with id `google`.
 */
export function googleProvider(
  env: Record<string, string | undefined> = process.env
): OAuthConfig<GoogleProfile> {
  const domain = googleWorkspaceDomain(env);
  return GoogleProvider({
    clientId: readEnvString(env, 'GOOGLE_CLIENT_ID') ?? '',
    clientSecret: readEnvString(env, 'GOOGLE_CLIENT_SECRET') ?? '',
    wellKnown: `${googleIssuerBaseUrl(env)}/.well-known/openid-configuration`,
    authorization: {
      params: {
        scope: 'openid email profile',
        // `hd` scopes Google's account chooser to the Workspace domain — advisory only; the real
        // enforcement is the profile-callback claim check below (see the module doc).
        ...(domain !== null ? { hd: domain } : {}),
      },
    },
    profile: (profile: GoogleProfile) => googleProfile(profile, domain),
  }) as OAuthConfig<GoogleProfile>;
}
