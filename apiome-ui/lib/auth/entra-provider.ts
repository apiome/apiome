/**
 * Microsoft Entra ID (azure) NextAuth provider (OLO-2.1, #4193).
 *
 * A custom OIDC provider definition instead of next-auth's built-in `azure-ad` for three reasons:
 *
 *   1. **Provider id must be `azure`.** The account-resolution engine gates Entra sign-ins behind
 *      the nOAuth hardening rules on `provider === 'azure'` (OLO-1.4), the auto-link trust list
 *      names `azure` (OLO-1.3), and `apiome.external_auth_providers` stores the identity under
 *      that value (OLO-1.2/2.2). The built-in id is `azure-ad`, which would silently miss all of
 *      those gates.
 *   2. **`oid` → provider_user_id.** The `oid` claim is the user's immutable directory object id;
 *      `sub` (the built-in's choice) is scoped per app registration, so rotating the registration
 *      would orphan every linked identity.
 *   3. **No Microsoft Graph photo fetch.** The built-in downloads the profile photo into a base64
 *      data-URI on every sign-in — an extra outbound call whose payload can overflow the session
 *      cookie. Identity resolution never needs the avatar.
 *
 * Env contract: `AZURE_AD_CLIENT_ID`, `AZURE_AD_CLIENT_SECRET`, and optional `AZURE_AD_TENANT`
 * (an Entra tenant id/domain, defaulting to `common` for multi-tenant sign-in). The provider is
 * only registered when the deployment configures it (see `entraIdProviderIfConfigured`), so an
 * unconfigured deployment never exposes a sign-in route that would redirect to Microsoft with an
 * undefined client id.
 *
 * Trust boundary: this module only maps the OIDC response onto a NextAuth user. Whether the
 * token's email claim may be believed is decided later by `resolveEntraEmailVerified`
 * (OLO-1.4, `account-resolution.ts`) inside the shared signIn callback — never here.
 */
import type { OAuthConfig } from 'next-auth/providers/oauth';
import { isProviderEnabled, readEnvString } from './provider-registry';

/**
 * The provider slug — the value stored in `external_auth_providers.provider` and matched by the
 * resolution engine's Entra-specific email gating. Never rename: `azure-ad` or similar would
 * bypass the nOAuth hardening (OLO-1.4) and orphan persisted identities.
 */
export const ENTRA_ID_PROVIDER_ID = 'azure';

/** Multi-tenant app registrations sign in through the `common` endpoint. */
const DEFAULT_TENANT = 'common';

/** The Entra ID id-token claims this module reads (all others pass through untouched). */
export interface EntraIdProfile extends Record<string, unknown> {
  /** Immutable directory object id — the stable provider_user_id (never use `sub`). */
  oid?: string;
  /** Per-app-registration subject; fallback only, for tokens missing `oid`. */
  sub?: string;
  name?: string;
  email?: string;
  preferred_username?: string;
}

/**
 * Whether this deployment configured Entra ID sign-in.
 *
 * Delegates to the provider registry (OLO-2.3) — the single source of the `azure` env
 * contract (`AZURE_AD_CLIENT_ID` + `AZURE_AD_CLIENT_SECRET`, both set and non-blank).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns True when both `AZURE_AD_CLIENT_ID` and `AZURE_AD_CLIENT_SECRET` are set and non-blank.
 */
export function isEntraIdConfigured(
  env: Record<string, string | undefined> = process.env
): boolean {
  return isProviderEnabled(ENTRA_ID_PROVIDER_ID, env);
}

/**
 * Map the raw Entra ID id-token claims onto the NextAuth user shape.
 *
 * `id` becomes `account.providerAccountId`, which the resolution engine persists as
 * `provider_user_id` — so it must be the immutable `oid` (falling back to `sub` only when a
 * token carries no `oid`, e.g. some personal-account variants). The raw claims themselves still
 * reach the signIn callback as `profile`, where the nOAuth email rules read them (OLO-1.4).
 *
 * @param profile Raw claims from the Entra ID id token.
 * @returns The NextAuth user: stable id, display name, email (untrusted until 1.4 proves it),
 *   and a null image (no Graph photo fetch — see the module doc).
 */
export function entraIdProfile(profile: EntraIdProfile) {
  return {
    id: (profile.oid ?? profile.sub ?? '') as string,
    name: profile.name ?? profile.preferred_username ?? null,
    email: profile.email ?? null,
    image: null,
  };
}

/**
 * Build the Entra ID OAuth provider config (OIDC authorization-code flow).
 *
 * Uses tenant-scoped OIDC discovery (the same `wellKnown` shape as next-auth's built-in
 * `azure-ad` provider, including the `appid` hint) and enforces PKCE plus the `state` and
 * `nonce` checks on every round-trip.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns A NextAuth OAuth provider with id `azure`.
 */
export function entraIdProvider(
  env: Record<string, string | undefined> = process.env
): OAuthConfig<EntraIdProfile> {
  const clientId = readEnvString(env, 'AZURE_AD_CLIENT_ID') ?? '';
  const tenant = readEnvString(env, 'AZURE_AD_TENANT') ?? DEFAULT_TENANT;

  return {
    id: ENTRA_ID_PROVIDER_ID,
    name: 'Microsoft Entra ID',
    type: 'oauth',
    wellKnown: `https://login.microsoftonline.com/${tenant}/v2.0/.well-known/openid-configuration?appid=${clientId}`,
    // `offline_access` makes Microsoft issue a refresh token on the code exchange, so the azure
    // identity row carries token-refresh data like the other providers (OLO-2.2, #4194).
    authorization: { params: { scope: 'openid profile email offline_access' } },
    idToken: true,
    checks: ['pkce', 'state', 'nonce'],
    clientId,
    clientSecret: readEnvString(env, 'AZURE_AD_CLIENT_SECRET') ?? '',
    profile: entraIdProfile,
  };
}

/**
 * The Entra ID provider as a spreadable list: `[provider]` when the deployment configured it,
 * `[]` otherwise. Keeps the NextAuth config declarative
 * (`providers: [github, gitlab, ...entraIdProviderIfConfigured()]`) while guaranteeing an
 * unconfigured deployment registers no `azure` sign-in route at all — such attempts then fall to
 * NextAuth's unknown-provider handling rather than a broken Microsoft redirect.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns A zero- or one-element provider list for spreading into `authOptions.providers`.
 */
export function entraIdProviderIfConfigured(
  env: Record<string, string | undefined> = process.env
): OAuthConfig<EntraIdProfile>[] {
  return isEntraIdConfigured(env) ? [entraIdProvider(env)] : [];
}
