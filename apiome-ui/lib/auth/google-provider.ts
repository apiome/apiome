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
import {
  GOOGLE_PROVIDER_ID,
  assertGoogleHostedDomain,
  googleIssuerBaseUrl,
  googleWorkspaceDomain,
  hostedDomainMatches,
  type GoogleProfile,
} from './google-workspace-domain';

// The provider slug, issuer base URL, Workspace-domain read, and the `hd` gate are the pure,
// engine-neutral core of Google sign-in; they were extracted to `google-workspace-domain.ts` so the
// Better Auth generic-OIDC provider (OLO-10.7) shares one implementation of the security-critical
// domain gate. Re-exported here so this module's existing importers (and `google-provider.test.ts`)
// keep their single import surface.
export {
  GOOGLE_PROVIDER_ID,
  assertGoogleHostedDomain,
  googleIssuerBaseUrl,
  googleWorkspaceDomain,
  hostedDomainMatches,
  type GoogleProfile,
};

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
