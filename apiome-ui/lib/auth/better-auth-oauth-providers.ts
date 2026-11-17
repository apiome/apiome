/**
 * Better Auth OAuth provider construction (OLO-10.7, #5002).
 *
 * Re-expresses the live sign-in providers — github, gitlab, azure, google, okta, aws, keycloak,
 * oidc, auth0, line, vk, wechat, atlassian, bitbucket, slack, linkedin, discord, salesforce, notion, figma, linear, dropbox, zoom, huggingface, vercel — on Better Auth's **generic OAuth2/OIDC** plugin, the Better Auth analogue of the
 * NextAuth factory map in `nextauth-oauth-providers.ts`. Every provider is driven from the shared
 * provider registry (`provider-registry.ts`) exactly as the NextAuth path is, so the registry stays
 * the single source of the enabled set and the mirror tests (`provider-registry-mirror.test.ts`,
 * `test_auth_provider_registry.py`) keep holding with no registry change.
 *
 * All use `genericOAuth` (not Better Auth's built-in `socialProviders`) for one decisive
 * reason: the built-in social providers hard-code their authorization/token endpoints, so they
 * cannot honour the OLO-7.4 endpoint/issuer overrides the mocked-provider e2e journey depends on.
 * The generic plugin exposes `authorizationUrl`/`tokenUrl`/`userInfoUrl`/`discoveryUrl`, so every
 * endpoint stays overridable via the same env vars the NextAuth path reads (`GITHUB_OAUTH_BASE_URL`,
 * `GITHUB_API_BASE_URL`, `GITLAB_BASE_URL`, `GOOGLE_ISSUER`, `OKTA_ISSUER`, `COGNITO_ISSUER`,
 * `KEYCLOAK_ISSUER`, `OIDC_ISSUER`, `AUTH0_ISSUER`, `SALESFORCE_ISSUER`,
 * `AZURE_AD_AUTHORITY_BASE_URL`, `AZURE_AD_TENANT`). The generic callback path (`/oauth2/callback/:id`) is exactly the prefix the
 * OLO-10.6 resolution adapter already recognises.
 *
 * What each provider re-attaches (identical policy to the NextAuth engine, proven by tests):
 *  - **Verified-email parity (OLO-2.5):** GitHub `/user/emails` verified flags, GitLab `confirmed_at`,
 *    Google's / Okta's / Cognito's / Keycloak's native `email_verified` — normalized onto the profile
 *    as `email_verified` before the resolution engine sees it (`verified-email.ts` pure helpers,
 *    reused verbatim).
 *  - **Google Workspace `hd` gate (OLO-9.2):** `assertGoogleHostedDomain` throws before resolution,
 *    so an out-of-domain account never lands an identity (`google-workspace-domain.ts`).
 *  - **Okta issuer discovery (OLO-9.3):** `OKTA_ISSUER` drives OIDC discovery; PKCE on; native
 *    `email_verified` fail-closed via `resolveOAuthEmailVerified` (`okta-issuer.ts`).
 *  - **Cognito issuer discovery (OLO-9.4):** `COGNITO_ISSUER` (user-pool issuer) drives OIDC
 *    discovery; PKCE on; native `email_verified` fail-closed (`cognito-issuer.ts`).
 *  - **Keycloak issuer discovery (OLO-9.5):** `KEYCLOAK_ISSUER` (realm issuer) drives OIDC
 *    discovery; PKCE on; native `email_verified` fail-closed (`keycloak-issuer.ts`).
 *  - **Generic OIDC (OLO-9.6):** `OIDC_ISSUER` drives OIDC discovery; optional `OIDC_DISPLAY_NAME`
 *    / `OIDC_SCOPES`; PKCE on; native `email_verified` fail-closed (`oidc-issuer.ts`).
 *  - **Auth0 issuer discovery (OLO-9.7):** `AUTH0_ISSUER` (tenant issuer) drives OIDC discovery;
 *    PKCE on; native `email_verified` fail-closed (`auth0-issuer.ts`).
 *  - **LINE Login (OLO-9.41):** fixed LINE OIDC endpoints (`access.line.me` / `api.line.me`); email
 *    requires an approved channel permission — `email_verified` honored when present, otherwise
 *    fail-closed link-first.
 *  - **VK ID (OLO-9.42):** fixed VK ID endpoints (`id.vk.com`); email returned with grant but no
 *    verified claim (Better Auth `vk()` hard-codes `emailVerified: false`) → fail-closed link-first.
 *  - **WeChat Open Platform (OLO-9.43):** QR Website App flow (`open.weixin.qq.com/connect/qrconnect`);
 *    custom `getToken` (GET `appid`/`secret` exchange); identity keyed on `unionid`||`openid`;
 *    **no email** → link-only.
 *  - **Atlassian (OLO-9.8):** fixed Atlassian endpoints (`auth.atlassian.com` / `api.atlassian.com/me`),
 *    `audience=api.atlassian.com`; PKCE on; `email_verified` from `/me` honored when present,
 *    otherwise fail-closed link-first.
 *  - **Bitbucket (OLO-9.9):** fixed Bitbucket Cloud endpoints (`bitbucket.org/site/oauth2`,
 *    `api.bitbucket.org/2.0/user`); the profile has no email, so `/2.0/user/emails` supplies the
 *    primary address and its confirmed flag (the GitHub `/user/emails` pattern).
 *  - **Slack (OLO-9.17):** Sign in with Slack over Slack's fixed OIDC discovery document
 *    (`slack.com/.well-known/openid-configuration`), scopes `openid profile email`; native
 *    `email_verified` claim fail-closed via `resolveOAuthEmailVerified`.
 *  - **LinkedIn (OLO-9.18):** Sign In with LinkedIn over LinkedIn's fixed OIDC discovery document
 *    (`www.linkedin.com/oauth/.well-known/openid-configuration`), scopes `openid profile email`;
 *    native `email_verified` claim fail-closed via `resolveOAuthEmailVerified`.
 *  - **Discord (OLO-9.19):** fixed Discord endpoints (`discord.com/api/oauth2`,
 *    `discord.com/api/users/@me`), scopes `identify email`; the profile's `verified` flag is
 *    normalized to `email_verified`, so an unverified Discord address is refused.
 *  - **Salesforce (OLO-9.20):** OIDC discovery on `SALESFORCE_ISSUER` (optional; default
 *    `login.salesforce.com`, set for a My Domain or a sandbox); PKCE on; native `email_verified`
 *    claim from the id token or `<issuer>/services/oauth2/userinfo`, fail-closed via
 *    `resolveOAuthEmailVerified` (`salesforce-issuer.ts`).
 *  - **Notion (OLO-9.21):** fixed Notion endpoints (`api.notion.com/v1/oauth`,
 *    `api.notion.com/v1/users/me`), `owner=user`, HTTP Basic code exchange, no scopes; the owner
 *    user's email carries no verified claim (Better Auth `notion()` hard-codes
 *    `emailVerified: false`) → fail-closed link-first.
 *  - **Figma (OLO-9.22):** fixed Figma endpoints (`www.figma.com/oauth`,
 *    `api.figma.com/v1/oauth/token`, `api.figma.com/v1/me`), scope `current_user:read`, HTTP Basic
 *    code exchange, PKCE on; the `/v1/me` email carries no verified claim (Better Auth `figma()`
 *    hard-codes `emailVerified: false`) → fail-closed link-first.
 *  - **Linear (OLO-9.23):** fixed Linear endpoints (`linear.app/oauth/authorize`,
 *    `api.linear.app/oauth/token`), scope `read`, client credentials in the exchange body, no
 *    PKCE; the user comes from the GraphQL `viewer` query (`api.linear.app/graphql`), whose email
 *    carries no verified claim (Better Auth `linear()` hard-codes `emailVerified: false`) →
 *    fail-closed link-first.
 *  - **Dropbox (OLO-9.24):** fixed Dropbox endpoints (`www.dropbox.com/oauth2/authorize`,
 *    `api.dropboxapi.com/oauth2/token`), scope `account_info.read`, client credentials in the
 *    exchange body, PKCE on; the user comes from a body-less POST to
 *    `api.dropboxapi.com/2/users/get_current_account`, whose `email_verified` flag is normalized
 *    fail-closed (true only when exactly `true`), so an unverified Dropbox address is refused.
 *  - **Zoom (OLO-9.25):** fixed Zoom endpoints (`zoom.us/oauth/authorize`, `zoom.us/oauth/token`),
 *    no scope parameter (a Zoom app's scopes are set on the app), client credentials in the
 *    exchange body, PKCE on; the user comes from `api.zoom.us/v2/users/me`, whose integer
 *    `verified` flag (`1` = verified email) is normalized fail-closed to `email_verified`, so an
 *    unverified Zoom address is refused.
 *  - **Hugging Face (OLO-9.26):** Sign in with Hugging Face over Hugging Face's fixed OIDC
 *    discovery document (`huggingface.co/.well-known/openid-configuration`), scopes
 *    `openid profile email`, PKCE on; the claims come from `huggingface.co/oauth/userinfo`, and
 *    the native `email_verified` claim is fail-closed via `resolveOAuthEmailVerified`.
 *  - **Vercel (OLO-9.27):** Sign in with Vercel on fixed endpoints mirrored from Better Auth's
 *    `vercel` provider (`vercel.com/oauth/authorize`, `api.vercel.com/login/oauth/token`), scopes
 *    `openid email profile`, client credentials in the exchange body, PKCE on (Vercel requires
 *    it); the claims come from `api.vercel.com/login/oauth/userinfo`, whose `email_verified` flag
 *    is re-stamped fail-closed (true only when exactly `true`), so an unverified Vercel address is
 *    refused.
 *  - **nOAuth hardening (OLO-1.4):** azure id-token claims (`oid`/`upn`/`xms_edov`/…) pass through
 *    untouched so the engine's `resolveEntraEmailVerified` still rejects a forged token.
 *  - **The account-resolution decision (OLO-1.x):** every callback runs through
 *    `resolveBetterAuthOAuthSignIn` (OLO-10.6). Admit → Better Auth establishes the session; any
 *    non-admit outcome (login error, onboarding, link) is steered to the engine's exact redirect
 *    path via the request-scoped {@link oauthRedirectOverrideStore} (see below).
 *
 * **Lifecycle placement (the piece OLO-10.6 deferred to this ticket).** Better Auth's generic
 * callback fetches the profile through `getUserInfo(tokens)` *before* it creates or links any user
 * (`plugins/generic-oauth/routes.mjs`); a custom `getUserInfo` therefore fully owns the decision. On
 * a non-admit it returns `null`, which makes Better Auth redirect to its OAuth error URL — and the
 * handler wrapper in `auth.ts` rewrites that redirect's `Location` to the engine's byte-identical
 * `/login?error=<code>` / `/signup/oauth?…` / linked-accounts path (OLO-1.5 contract). The override
 * travels on an {@link AsyncLocalStorage} scoped to the single callback request, so it is race-free.
 *
 * Scope note (OLO-10.7): this module wires the providers, the normalization, the `hd` gate, and the
 * resolution invocation, proven by `tests/better-auth-oauth-providers.test.ts`. Per-request
 * DB-over-env provider resolution is now implemented (OLO-10.8): `auth.ts` feeds the resolver's merged
 * env into {@link buildGenericOAuthConfigs} and rebuilds the instance when {@link providerConfigSignature}
 * changes. Account/identity-table parity (10.9) and the live mock-provider e2e journey (10.13) are
 * sequenced after this ticket.
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import { createHash } from 'node:crypto';

import type { GenericOAuthConfig } from 'better-auth/plugins/generic-oauth';
import type { OAuth2Tokens, OAuth2UserInfo } from 'better-auth/oauth2';

import {
  AUTH_ERROR_CODES,
  canonicalizeEmail,
  resolveEntraEmailVerified,
  resolveOAuthEmailVerified,
  loginErrorRedirect,
  type OAuthSignInResult,
  type ResolutionStore,
} from './account-resolution';
import {
  resolveBetterAuthOAuthSignIn,
  type BetterAuthOAuthContext,
} from './better-auth-account-resolution';
import { resolutionStore } from './resolution-store';
import { enabledProviders, readEnvString } from './provider-registry';
import {
  BITBUCKET_OAUTH_SCOPE,
  GITHUB_OAUTH_SCOPE,
  GITLAB_OAUTH_SCOPE,
  githubApiBaseUrl,
  gitlabBaseUrl,
  resolveGithubVerifiedEmail,
  resolveGitlabEmailVerified,
  type GithubEmailEntry,
  resolveBitbucketVerifiedEmail,
} from './verified-email';
import {
  assertGoogleHostedDomain,
  googleIssuerBaseUrl,
  googleWorkspaceDomain,
  type GoogleProfile,
} from './google-workspace-domain';
import { oktaIssuerBaseUrl } from './okta-issuer';
import { cognitoIssuerBaseUrl } from './cognito-issuer';
import { keycloakIssuerBaseUrl } from './keycloak-issuer';
import { oidcIssuerBaseUrl, oidcScopes } from './oidc-issuer';
import { auth0IssuerBaseUrl } from './auth0-issuer';
import { salesforceIssuerBaseUrl, salesforceUserInfoUrl } from './salesforce-issuer';
import { entraAuthorityBaseUrl, entraIdProfile, type EntraIdProfile } from './entra-provider';

/* ── Request-scoped redirect override ──────────────────────────────────────────────────────── */

/**
 * Per-request carrier that lets a provider's `getUserInfo` steer the callback's final redirect to
 * the account-resolution engine's exact path. `auth.ts` runs `auth.handler` inside this async
 * context (`runWithOauthRedirectOverride`); `getUserInfo` writes the path on a non-admit
 * (`setOauthRedirectOverride`); the handler wrapper then rewrites the redirect `Location`
 * (`applyOauthRedirectOverride`). Scoped to the single callback request, so concurrent sign-ins
 * never see each other's override.
 */
export const oauthRedirectOverrideStore = new AsyncLocalStorage<{ redirect: string | null }>();

/**
 * Run `fn` inside a fresh redirect-override scope. `auth.ts`'s `betterAuthHandler` wraps every
 * Better Auth request in this so `getUserInfo` (deep inside the generic-OAuth callback) can publish
 * a redirect back out to the handler boundary.
 *
 * @param fn The work to run (typically `auth.handler(request)`).
 * @returns Whatever `fn` resolves to.
 */
export function runWithOauthRedirectOverride<T>(fn: () => Promise<T>): Promise<T> {
  return oauthRedirectOverrideStore.run({ redirect: null }, fn);
}

/**
 * Record the exact path the callback should redirect to instead of completing the sign-in. No-ops
 * when called outside a redirect-override scope (e.g. a unit test driving `getUserInfo` directly),
 * so the resolution outcome is still returned to the caller.
 *
 * @param path The engine's redirect path (`/login?error=…`, `/signup/oauth?…`, linked-accounts).
 */
export function setOauthRedirectOverride(path: string): void {
  const scope = oauthRedirectOverrideStore.getStore();
  if (scope) scope.redirect = path;
}

/**
 * The redirect path a provider's `getUserInfo` published for the current request, or null when the
 * sign-in was admitted (or no scope is active).
 *
 * @returns The override path, or null.
 */
export function getOauthRedirectOverride(): string | null {
  return oauthRedirectOverrideStore.getStore()?.redirect ?? null;
}

/**
 * Rewrite a Better Auth redirect `Response`'s `Location` to the engine's override path when one was
 * published for this request. Leaves non-redirect responses and un-overridden redirects untouched,
 * so an admitted sign-in flows to Better Auth's own callback URL exactly as normal.
 *
 * @param response The response Better Auth's handler produced.
 * @returns The response, with `Location` swapped to the engine's path when an override is set.
 */
export function applyOauthRedirectOverride(response: Response): Response {
  const override = getOauthRedirectOverride();
  if (!override) return response;
  if (response.status < 300 || response.status >= 400) return response;
  const headers = new Headers(response.headers);
  headers.set('Location', override);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

/* ── Token / profile helpers ───────────────────────────────────────────────────────────────── */

/** Minimal fetch shape, injectable so tests never touch the network. */
export type FetchLike = (
  url: string,
  init: {
    headers: Record<string, string>;
    method?: string;
    body?: string;
  }
) => Promise<{ ok: boolean; json: () => Promise<unknown> }>;

/** Remove a single trailing slash so `${base}/path` never doubles the separator. */
function stripTrailingSlash(url: string): string {
  return url.endsWith('/') ? url.slice(0, -1) : url;
}

/**
 * Base URL of GitHub's OAuth **web** endpoints (`/login/oauth/authorize`, `…/access_token`).
 * Overridable via `GITHUB_OAUTH_BASE_URL` for the mocked-provider e2e journey (OLO-7.4); defaults
 * to the real host. (This was the sole GitHub base-URL helper once NextAuth and its provider factory
 * were removed at the OLO-10.14 cutover.)
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The base URL without a trailing slash.
 */
export function githubOauthWebBaseUrl(
  env: Record<string, string | undefined> = process.env
): string {
  return stripTrailingSlash(readEnvString(env, 'GITHUB_OAUTH_BASE_URL') ?? 'https://github.com');
}

/**
 * Fetch a JSON resource with the OAuth bearer token, failing **soft**: any transport error, non-2xx
 * response, or malformed body yields null (the caller then resolves to unverified rather than
 * crashing the whole sign-in round trip — the same fail-closed posture as `verified-email.ts`).
 *
 * @param url Absolute URL to fetch.
 * @param accessToken The OAuth access token from the code exchange.
 * @param fetchImpl Fetch implementation (injectable for tests; defaults to global fetch).
 * @param extraHeaders Extra request headers a provider's API requires (e.g. `Notion-Version`).
 * @returns The parsed JSON body, or null when it could not be retrieved.
 */
async function fetchJsonWithToken(
  url: string,
  accessToken: string,
  fetchImpl: FetchLike,
  extraHeaders: Record<string, string> = {}
): Promise<unknown> {
  try {
    const res = await fetchImpl(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/json',
        'User-Agent': 'apiome',
        ...extraHeaders,
      },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Decode the claim set from a JWT (an OIDC id token) without verifying its signature: split off the
 * payload segment, base64url-decode it, and JSON-parse. Signature verification is Better Auth's job
 * during the code exchange; this only reads the already-validated claims. Fail-soft to null on any
 * malformed input.
 *
 * @param idToken The compact-serialization JWT, or null/undefined.
 * @returns The decoded claim object, or null when the token is absent or unparseable.
 */
export function decodeJwtClaims(idToken: string | null | undefined): Record<string, unknown> | null {
  if (typeof idToken !== 'string') return null;
  const segments = idToken.split('.');
  if (segments.length < 2) return null;
  try {
    const json = Buffer.from(segments[1], 'base64url').toString('utf8');
    const claims = JSON.parse(json);
    return claims && typeof claims === 'object' ? (claims as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/* ── Per-provider profile normalization ────────────────────────────────────────────────────── */

/**
 * The facts a provider's `getUserInfo` gathers before the resolution engine runs: the stable
 * provider-side account id, the raw profile (with `email_verified` normalized onto it where the
 * provider does not carry it natively), and the display fields Better Auth stores on the user.
 */
export interface NormalizedOAuthProfile {
  /** Stable provider-side id → `account.providerAccountId` (github/gitlab `id`, `sub`, azure `oid`). */
  accountId: string;
  /** Raw provider profile / id-token claims, with `email_verified` stamped for github/gitlab. */
  profile: Record<string, unknown>;
  /** The resolved sign-in email (github may adopt the primary address from `/user/emails`). */
  email: string | null;
  /** Display name for the Better Auth user record. */
  name: string | null;
  /** Avatar URL for the Better Auth user record (null for azure — no Graph photo fetch). */
  image: string | null;
}

/**
 * Normalize a GitHub sign-in: fetch `/user`, consult `/user/emails`, and stamp the resolved
 * address + `email_verified` onto the profile (OLO-2.5 parity). Both endpoints honour the
 * `GITHUB_API_BASE_URL` override (OLO-7.4).
 */
async function normalizeGithub(
  tokens: OAuth2Tokens,
  env: Record<string, string | undefined>,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const apiBase = githubApiBaseUrl(env);
  const profileBody = await fetchJsonWithToken(`${apiBase}/user`, accessToken, fetchImpl);
  const profile: Record<string, unknown> =
    profileBody && typeof profileBody === 'object' ? { ...(profileBody as object) } : {};
  const emailsBody = await fetchJsonWithToken(`${apiBase}/user/emails`, accessToken, fetchImpl);
  const entries = Array.isArray(emailsBody) ? (emailsBody as GithubEmailEntry[]) : null;

  const resolution = resolveGithubVerifiedEmail(
    typeof profile.email === 'string' ? profile.email : null,
    entries
  );
  profile.email = resolution.email;
  profile.email_verified = resolution.emailVerified;

  return {
    accountId: profile.id != null ? String(profile.id) : '',
    profile,
    email: resolution.email,
    name:
      (typeof profile.name === 'string' && profile.name) ||
      (typeof profile.login === 'string' && profile.login) ||
      null,
    image: typeof profile.avatar_url === 'string' ? profile.avatar_url : null,
  };
}

/**
 * Normalize a GitLab sign-in: fetch `/api/v4/user` and stamp `email_verified` from the
 * `confirmed_at` evidence (OLO-2.5 parity). The endpoint honours the `GITLAB_BASE_URL` override.
 */
async function normalizeGitlab(
  tokens: OAuth2Tokens,
  env: Record<string, string | undefined>,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = await fetchJsonWithToken(`${gitlabBaseUrl(env)}/api/v4/user`, accessToken, fetchImpl);
  const profile: Record<string, unknown> =
    body && typeof body === 'object' ? { ...(body as object) } : {};
  profile.email_verified = resolveGitlabEmailVerified(profile);

  const accountId = profile.id != null ? String(profile.id) : profile.sub != null ? String(profile.sub) : '';
  return {
    accountId,
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name:
      (typeof profile.name === 'string' && profile.name) ||
      (typeof profile.username === 'string' && profile.username) ||
      null,
    image: typeof profile.avatar_url === 'string' ? profile.avatar_url : null,
  };
}

/**
 * Normalize a Google sign-in: decode the id-token claims (native `email_verified` + `hd`) and
 * enforce the Workspace-domain gate before anything else, so an out-of-domain account is rejected
 * (OLO-9.2). Discovery is pointed at `googleIssuerBaseUrl`, so the e2e journey can substitute a mock
 * issuer (OLO-7.4).
 *
 * @throws Error (via {@link assertGoogleHostedDomain}) when the domain gate rejects the account.
 */
function normalizeGoogle(
  tokens: OAuth2Tokens,
  env: Record<string, string | undefined>
): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as GoogleProfile;
  assertGoogleHostedDomain(claims, googleWorkspaceDomain(env));
  return {
    accountId: typeof claims.sub === 'string' ? claims.sub : '',
    profile: claims,
    email: typeof claims.email === 'string' ? claims.email : null,
    name: typeof claims.name === 'string' ? claims.name : null,
    image: typeof claims.picture === 'string' ? claims.picture : null,
  };
}

/**
 * Normalize an azure (Microsoft Entra ID) sign-in: decode the id-token claims and pass them through
 * untouched — the engine's `resolveEntraEmailVerified` reads `oid`/`upn`/`xms_edov`/`email_verified`
 * for the nOAuth hardening (OLO-1.4). `oid` (falling back to `sub`) is the stable provider id.
 */
function normalizeAzure(tokens: OAuth2Tokens): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as EntraIdProfile;
  const mapped = entraIdProfile(claims);
  return {
    accountId: mapped.id ? String(mapped.id) : '',
    profile: claims as Record<string, unknown>,
    email: mapped.email,
    name: mapped.name,
    image: null,
  };
}

/**
 * Normalize an Okta sign-in: decode the id-token claims (native `email_verified`) and pass them
 * through so `resolveOAuthEmailVerified` fail-closes when the claim is absent/false (OLO-9.3).
 * Discovery is pointed at `oktaIssuerBaseUrl` (`OKTA_ISSUER`).
 */
function normalizeOkta(tokens: OAuth2Tokens): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as Record<string, unknown>;
  return {
    accountId: typeof claims.sub === 'string' ? claims.sub : '',
    profile: claims,
    email: typeof claims.email === 'string' ? claims.email : null,
    name: typeof claims.name === 'string' ? claims.name : null,
    image: typeof claims.picture === 'string' ? claims.picture : null,
  };
}

/**
 * Normalize an Amazon Cognito (`aws`) sign-in: decode the id-token claims (native
 * `email_verified`) and pass them through so `resolveOAuthEmailVerified` fail-closes when the
 * claim is absent/false (OLO-9.4). Discovery is pointed at `cognitoIssuerBaseUrl`
 * (`COGNITO_ISSUER` = user-pool issuer). Cognito does not emit a picture claim by default.
 */
function normalizeAws(tokens: OAuth2Tokens): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as Record<string, unknown>;
  return {
    accountId: typeof claims.sub === 'string' ? claims.sub : '',
    profile: claims,
    email: typeof claims.email === 'string' ? claims.email : null,
    name:
      (typeof claims.name === 'string' && claims.name) ||
      (typeof claims['cognito:username'] === 'string' && claims['cognito:username']) ||
      null,
    image: typeof claims.picture === 'string' ? claims.picture : null,
  };
}

/**
 * Normalize a Keycloak sign-in: decode the id-token claims (native `email_verified`) and pass
 * them through so `resolveOAuthEmailVerified` fail-closes when the claim is absent/false
 * (OLO-9.5). Discovery is pointed at `keycloakIssuerBaseUrl` (`KEYCLOAK_ISSUER` = realm issuer).
 * Falls back to `preferred_username` when `name` is absent (common Keycloak default mapper set).
 */
function normalizeKeycloak(tokens: OAuth2Tokens): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as Record<string, unknown>;
  return {
    accountId: typeof claims.sub === 'string' ? claims.sub : '',
    profile: claims,
    email: typeof claims.email === 'string' ? claims.email : null,
    name:
      (typeof claims.name === 'string' && claims.name) ||
      (typeof claims.preferred_username === 'string' && claims.preferred_username) ||
      null,
    image: typeof claims.picture === 'string' ? claims.picture : null,
  };
}

/**
 * Normalize a generic OIDC sign-in: decode the id-token claims (native `email_verified`) and
 * pass them through so `resolveOAuthEmailVerified` fail-closes when the claim is absent/false
 * (OLO-9.6). Discovery is pointed at `oidcIssuerBaseUrl` (`OIDC_ISSUER`). Falls back to
 * `preferred_username` when `name` is absent (common default mapper set across IdPs).
 */
function normalizeOidc(tokens: OAuth2Tokens): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as Record<string, unknown>;
  return {
    accountId: typeof claims.sub === 'string' ? claims.sub : '',
    profile: claims,
    email: typeof claims.email === 'string' ? claims.email : null,
    name:
      (typeof claims.name === 'string' && claims.name) ||
      (typeof claims.preferred_username === 'string' && claims.preferred_username) ||
      null,
    image: typeof claims.picture === 'string' ? claims.picture : null,
  };
}

/**
 * Normalize an Auth0 sign-in: decode the id-token claims (native `email_verified`) and pass
 * them through so `resolveOAuthEmailVerified` fail-closes when the claim is absent/false
 * (OLO-9.7). Discovery is pointed at `auth0IssuerBaseUrl` (`AUTH0_ISSUER` = tenant issuer,
 * e.g. `https://acme.auth0.com`). Falls back to `nickname` when `name` is absent (common Auth0
 * default).
 */
function normalizeAuth0(tokens: OAuth2Tokens): NormalizedOAuthProfile {
  const claims = (decodeJwtClaims(tokens.idToken) ?? {}) as Record<string, unknown>;
  return {
    accountId: typeof claims.sub === 'string' ? claims.sub : '',
    profile: claims,
    email: typeof claims.email === 'string' ? claims.email : null,
    name:
      (typeof claims.name === 'string' && claims.name) ||
      (typeof claims.nickname === 'string' && claims.nickname) ||
      null,
    image: typeof claims.picture === 'string' ? claims.picture : null,
  };
}

/** LINE Login v2.1 userinfo endpoint (Better Auth `line()` helper). */
const LINE_USERINFO_URL = 'https://api.line.me/oauth2/v2.1/userinfo';

/** VK ID endpoints (Better Auth `vk()` helper). */
const VK_AUTHORIZE_URL = 'https://id.vk.com/authorize';
const VK_TOKEN_URL = 'https://id.vk.com/oauth2/auth';
const VK_USERINFO_URL = 'https://id.vk.com/oauth2/user_info';

/** WeChat Open Platform Website App endpoints (Better Auth `wechat()` helper). */
const WECHAT_AUTHORIZE_URL = 'https://open.weixin.qq.com/connect/qrconnect#wechat_redirect';
const WECHAT_TOKEN_URL = 'https://api.weixin.qq.com/sns/oauth2/access_token';
const WECHAT_USERINFO_URL = 'https://api.weixin.qq.com/sns/userinfo';

/** Atlassian OAuth 2.0 (3LO) endpoints and the User Identity API profile resource (OLO-9.8). */
const ATLASSIAN_AUTHORIZE_URL = 'https://auth.atlassian.com/authorize';
const ATLASSIAN_TOKEN_URL = 'https://auth.atlassian.com/oauth/token';
const ATLASSIAN_USERINFO_URL = 'https://api.atlassian.com/me';
/** The `audience` Atlassian's authorize endpoint requires for tokens that call `api.atlassian.com`. */
const ATLASSIAN_AUDIENCE = 'api.atlassian.com';

/** Bitbucket Cloud OAuth 2.0 endpoints and the 2.0 REST API user resources (OLO-9.9). */
const BITBUCKET_AUTHORIZE_URL = 'https://bitbucket.org/site/oauth2/authorize';
const BITBUCKET_TOKEN_URL = 'https://bitbucket.org/site/oauth2/access_token';
const BITBUCKET_USERINFO_URL = 'https://api.bitbucket.org/2.0/user';
/** The emails list, asked for at the API's largest page so the primary address is on page one. */
const BITBUCKET_EMAILS_URL = 'https://api.bitbucket.org/2.0/user/emails?pagelen=100';

/** Sign in with Slack: the fixed OIDC discovery document and its userinfo resource (OLO-9.17). */
const SLACK_DISCOVERY_URL = 'https://slack.com/.well-known/openid-configuration';
const SLACK_USERINFO_URL = 'https://slack.com/api/openid.connect.userInfo';
/** Slack's namespaced claim carrying the Slack user id (the same value as `sub`). */
const SLACK_USER_ID_CLAIM = 'https://slack.com/user_id';

/** Sign In with LinkedIn: the fixed OIDC discovery document and its userinfo resource (OLO-9.18). */
const LINKEDIN_DISCOVERY_URL = 'https://www.linkedin.com/oauth/.well-known/openid-configuration';
const LINKEDIN_USERINFO_URL = 'https://api.linkedin.com/v2/userinfo';

/** Discord OAuth 2.0: fixed endpoints, mirrored from Better Auth's `discord` provider (OLO-9.19). */
const DISCORD_AUTHORIZE_URL = 'https://discord.com/api/oauth2/authorize';
const DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token';
const DISCORD_USERINFO_URL = 'https://discord.com/api/users/@me';
/** Discord's image CDN, which serves user avatars and the default (embed) avatars. */
const DISCORD_CDN_URL = 'https://cdn.discordapp.com';

/** Notion OAuth 2.0: fixed endpoints, mirrored from Better Auth's `notion` provider (OLO-9.21). */
const NOTION_AUTHORIZE_URL = 'https://api.notion.com/v1/oauth/authorize';
const NOTION_TOKEN_URL = 'https://api.notion.com/v1/oauth/token';
const NOTION_USERINFO_URL = 'https://api.notion.com/v1/users/me';
/** The Notion API version sent as `Notion-Version` (required on every API call but the exchange). */
const NOTION_API_VERSION = '2022-06-28';

/** Figma OAuth 2.0: fixed endpoints, mirrored from Better Auth's `figma` provider (OLO-9.22). */
const FIGMA_AUTHORIZE_URL = 'https://www.figma.com/oauth';
const FIGMA_TOKEN_URL = 'https://api.figma.com/v1/oauth/token';
const FIGMA_USERINFO_URL = 'https://api.figma.com/v1/me';

/** Linear OAuth 2.0: fixed endpoints, mirrored from Better Auth's `linear` provider (OLO-9.23). */
const LINEAR_AUTHORIZE_URL = 'https://linear.app/oauth/authorize';
const LINEAR_TOKEN_URL = 'https://api.linear.app/oauth/token';
/** Linear has no REST userinfo endpoint: the signed-in user is the GraphQL `viewer`. */
const LINEAR_GRAPHQL_URL = 'https://api.linear.app/graphql';
/** The `viewer` fields the normalizer maps — the identity subset of Better Auth's `linear()` query. */
const LINEAR_VIEWER_QUERY = 'query { viewer { id name email avatarUrl } }';

/** Dropbox OAuth 2.0: fixed endpoints, mirrored from Better Auth's `dropbox` provider (OLO-9.24). */
const DROPBOX_AUTHORIZE_URL = 'https://www.dropbox.com/oauth2/authorize';
const DROPBOX_TOKEN_URL = 'https://api.dropboxapi.com/oauth2/token';
/** Dropbox's user resource is an RPC endpoint: a POST with no body, not a GET. */
const DROPBOX_USERINFO_URL = 'https://api.dropboxapi.com/2/users/get_current_account';

/** Zoom OAuth 2.0: fixed endpoints, mirrored from Better Auth's `zoom` provider (OLO-9.25). */
const ZOOM_AUTHORIZE_URL = 'https://zoom.us/oauth/authorize';
const ZOOM_TOKEN_URL = 'https://zoom.us/oauth/token';
const ZOOM_USERINFO_URL = 'https://api.zoom.us/v2/users/me';

/**
 * Sign in with Hugging Face: the fixed OIDC discovery document and its userinfo resource
 * (OLO-9.26).
 */
const HUGGINGFACE_DISCOVERY_URL = 'https://huggingface.co/.well-known/openid-configuration';
const HUGGINGFACE_USERINFO_URL = 'https://huggingface.co/oauth/userinfo';

/** Sign in with Vercel: fixed endpoints, mirrored from Better Auth's `vercel` provider (OLO-9.27). */
const VERCEL_AUTHORIZE_URL = 'https://vercel.com/oauth/authorize';
const VERCEL_TOKEN_URL = 'https://api.vercel.com/login/oauth/token';
const VERCEL_USERINFO_URL = 'https://api.vercel.com/login/oauth/userinfo';

/**
 * Normalize a LINE sign-in (OLO-9.41): prefer id-token claims (email arrives only when the
 * channel has approved email permission and the `email` scope was granted); fall back to the
 * LINE userinfo endpoint when the id token is absent. `email_verified` is honored when the claim
 * arrives; otherwise `resolveOAuthEmailVerified` fail-closes to link-first.
 */
async function normalizeLine(
  tokens: OAuth2Tokens,
  _env: Record<string, string | undefined>,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  let claims = (decodeJwtClaims(tokens.idToken) ?? null) as Record<string, unknown> | null;
  if (!claims && tokens.accessToken) {
    const body = await fetchJsonWithToken(LINE_USERINFO_URL, tokens.accessToken, fetchImpl);
    if (body && typeof body === 'object') {
      claims = body as Record<string, unknown>;
    }
  }
  const profile = claims ?? {};
  return {
    accountId: typeof profile.sub === 'string' ? profile.sub : '',
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name: typeof profile.name === 'string' ? profile.name : null,
    image: typeof profile.picture === 'string' ? profile.picture : null,
  };
}

/**
 * Fetch VK ID user_info via POST form body (`access_token` + `client_id`), matching Better Auth's
 * `vk()` helper. Fail-soft to null on any transport/parse error.
 */
async function fetchVkUserInfo(
  accessToken: string,
  clientId: string,
  fetchImpl: FetchLike
): Promise<Record<string, unknown> | null> {
  try {
    const formBody = new URLSearchParams({
      access_token: accessToken,
      client_id: clientId,
    }).toString();
    const res = await fetchImpl(VK_USERINFO_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Accept: 'application/json',
        'User-Agent': 'apiome',
      },
      body: formBody,
    });
    if (!res.ok) return null;
    const body = await res.json();
    return body && typeof body === 'object' ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * Normalize a VK ID sign-in (OLO-9.42): POST `user_info` with the access token and client id,
 * then map the nested `user` object. VK returns email with the grant but does **not** assert a
 * verified claim (Better Auth hard-codes `emailVerified: false`) — leave `email_verified` unset
 * so `resolveOAuthEmailVerified` fail-closes to link-first. Do not treat `user.verified` (VK
 * account badge) as email verification.
 */
async function normalizeVk(
  tokens: OAuth2Tokens,
  env: Record<string, string | undefined>,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const clientId = readEnvString(env, 'VK_CLIENT_ID') ?? '';
  const body = accessToken ? await fetchVkUserInfo(accessToken, clientId, fetchImpl) : null;
  const user =
    body && typeof body.user === 'object' && body.user !== null
      ? (body.user as Record<string, unknown>)
      : {};
  const first = typeof user.first_name === 'string' ? user.first_name : '';
  const last = typeof user.last_name === 'string' ? user.last_name : '';
  const name = `${first} ${last}`.trim() || null;
  return {
    accountId: typeof user.user_id === 'string' ? user.user_id : '',
    profile: user,
    email: typeof user.email === 'string' ? user.email : null,
    name,
    image: typeof user.avatar === 'string' ? user.avatar : null,
  };
}

/**
 * Exchange a WeChat authorization code for tokens via GET query params (`appid`/`secret`/`code`),
 * matching Better Auth's `wechat()` helper. WeChat is non-standard (no POST body, no `client_id`).
 * Stashes `openid`/`unionid` on `tokens.raw` for {@link normalizeWechat}.
 *
 * @param data Code-exchange inputs from Better Auth's generic-OAuth callback.
 * @param env Environment carrying `WECHAT_CLIENT_ID` / `WECHAT_CLIENT_SECRET`.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns OAuth2 tokens plus `raw.openid` / `raw.unionid`.
 */
export async function exchangeWechatAuthorizationCode(
  data: { code: string; redirectURI: string; codeVerifier?: string; deviceId?: string },
  env: Record<string, string | undefined> = process.env,
  fetchImpl: FetchLike = fetch as unknown as FetchLike
): Promise<OAuth2Tokens> {
  const appid = readEnvString(env, 'WECHAT_CLIENT_ID') ?? '';
  const secret = readEnvString(env, 'WECHAT_CLIENT_SECRET') ?? '';
  const url =
    WECHAT_TOKEN_URL +
    '?' +
    new URLSearchParams({
      appid,
      secret,
      code: data.code,
      grant_type: 'authorization_code',
    }).toString();
  const res = await fetchImpl(url, {
    method: 'GET',
    headers: { Accept: 'application/json', 'User-Agent': 'apiome' },
  });
  if (!res.ok) {
    throw new Error('WeChat token exchange failed with a non-2xx response');
  }
  const body = (await res.json()) as Record<string, unknown>;
  if (body.errcode != null) {
    throw new Error(
      `WeChat token exchange failed: ${typeof body.errmsg === 'string' ? body.errmsg : 'unknown error'}`
    );
  }
  const accessToken = typeof body.access_token === 'string' ? body.access_token : undefined;
  const refreshToken = typeof body.refresh_token === 'string' ? body.refresh_token : undefined;
  const expiresIn = typeof body.expires_in === 'number' ? body.expires_in : undefined;
  const scopeStr = typeof body.scope === 'string' ? body.scope : '';
  return {
    tokenType: 'Bearer',
    accessToken,
    refreshToken,
    accessTokenExpiresAt:
      typeof expiresIn === 'number' ? new Date(Date.now() + expiresIn * 1000) : undefined,
    scopes: scopeStr ? scopeStr.split(',') : undefined,
    raw: {
      openid: typeof body.openid === 'string' ? body.openid : undefined,
      unionid: typeof body.unionid === 'string' ? body.unionid : undefined,
    },
  };
}

/**
 * Normalize a WeChat Open Platform sign-in (OLO-9.43): fetch `/sns/userinfo` with
 * `access_token` + `openid` from the custom token exchange. Identity is keyed on
 * `unionid` when present (stable across apps under the same open-platform account), else
 * `openid`. WeChat exposes **no email** → leave email null so the engine fail-closes to
 * link-only (`OAuthEmailRequired` on fresh sign-in).
 */
async function normalizeWechat(
  tokens: OAuth2Tokens,
  _env: Record<string, string | undefined>,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const raw = tokens.raw && typeof tokens.raw === 'object' ? tokens.raw : {};
  const openid = typeof raw.openid === 'string' ? raw.openid : '';
  let profile: Record<string, unknown> = {};
  if (accessToken && openid) {
    const url =
      WECHAT_USERINFO_URL +
      '?' +
      new URLSearchParams({
        access_token: accessToken,
        openid,
        lang: 'zh_CN',
      }).toString();
    try {
      const res = await fetchImpl(url, {
        method: 'GET',
        headers: { Accept: 'application/json', 'User-Agent': 'apiome' },
      });
      if (res.ok) {
        const body = await res.json();
        if (body && typeof body === 'object' && (body as Record<string, unknown>).errcode == null) {
          profile = body as Record<string, unknown>;
        }
      }
    } catch {
      // Fail-soft: keep empty profile; identity still keys on token openid/unionid below.
    }
  }
  const profileOpenid = typeof profile.openid === 'string' ? profile.openid : openid;
  const unionid =
    typeof profile.unionid === 'string'
      ? profile.unionid
      : typeof raw.unionid === 'string'
        ? raw.unionid
        : '';
  // Prefer unionid (cross-app) when the open-platform account has bound multiple apps.
  const accountId = unionid || profileOpenid;
  return {
    accountId,
    profile: {
      ...profile,
      openid: profileOpenid || undefined,
      unionid: unionid || undefined,
    },
    email: null,
    name: typeof profile.nickname === 'string' ? profile.nickname : null,
    image: typeof profile.headimgurl === 'string' ? profile.headimgurl : null,
  };
}

/**
 * Normalize an Atlassian sign-in (OLO-9.8): fetch the User Identity API `/me` resource with the
 * access token and map `account_id` / `email` / `name` / `picture`. The profile is passed through
 * untouched, so `resolveOAuthEmailVerified` honors `email_verified` only when Atlassian sends it
 * as true; an absent or false claim fail-closes to link-first. A failed fetch yields an empty
 * profile (no account id, no email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeAtlassian(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(ATLASSIAN_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const profile: Record<string, unknown> =
    body && typeof body === 'object' ? { ...(body as object) } : {};
  return {
    accountId: typeof profile.account_id === 'string' ? profile.account_id : '',
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name:
      (typeof profile.name === 'string' && profile.name) ||
      (typeof profile.nickname === 'string' && profile.nickname) ||
      null,
    image: typeof profile.picture === 'string' ? profile.picture : null,
  };
}

/**
 * Normalize a Bitbucket sign-in (OLO-9.9): fetch `/2.0/user`, then `/2.0/user/emails` — the profile
 * itself carries no email — and stamp the primary address + `email_verified` (its confirmed flag)
 * onto the profile before the resolution engine runs. The identity is keyed on the Bitbucket
 * `uuid` (falling back to the Atlassian `account_id`); the mutable `username` is never the key.
 * A failed fetch yields no account id / no email, which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeBitbucket(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(BITBUCKET_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const profile: Record<string, unknown> =
    body && typeof body === 'object' ? { ...(body as object) } : {};
  const emailsBody = accessToken
    ? await fetchJsonWithToken(BITBUCKET_EMAILS_URL, accessToken, fetchImpl)
    : null;

  const resolution = resolveBitbucketVerifiedEmail(emailsBody);
  profile.email = resolution.email;
  profile.email_verified = resolution.emailVerified;

  const links = profile.links as { avatar?: { href?: unknown } } | null | undefined;
  const avatar = links?.avatar?.href;
  return {
    accountId:
      (typeof profile.uuid === 'string' && profile.uuid) ||
      (typeof profile.account_id === 'string' && profile.account_id) ||
      '',
    profile,
    email: resolution.email,
    name:
      (typeof profile.display_name === 'string' && profile.display_name) ||
      (typeof profile.nickname === 'string' && profile.nickname) ||
      (typeof profile.username === 'string' && profile.username) ||
      null,
    image: typeof avatar === 'string' ? avatar : null,
  };
}

/**
 * Normalize a Sign in with Slack callback (OLO-9.17): prefer the id-token claims; fall back to
 * Slack's `openid.connect.userInfo` resource when the id token is absent. Slack answers that
 * resource with HTTP 200 and `ok: false` on a bad token, so such a body is discarded. The claims
 * pass through untouched, so `resolveOAuthEmailVerified` honors `email_verified` only when Slack
 * sends it as true; an absent or false claim fail-closes to link-first. The identity is keyed on
 * `sub` (the Slack user id), falling back to the namespaced `https://slack.com/user_id` claim.
 *
 * @param tokens The tokens from the code exchange (`idToken`, then `accessToken`, are read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine; empty (no account id, no email) when
 *   neither source yields claims, which the engine refuses.
 */
async function normalizeSlack(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  let claims = decodeJwtClaims(tokens.idToken);
  if (!claims && tokens.accessToken) {
    const body = await fetchJsonWithToken(SLACK_USERINFO_URL, tokens.accessToken, fetchImpl);
    if (body && typeof body === 'object' && (body as Record<string, unknown>).ok !== false) {
      claims = body as Record<string, unknown>;
    }
  }
  const profile = claims ?? {};
  const slackUserId = profile[SLACK_USER_ID_CLAIM];
  return {
    accountId:
      (typeof profile.sub === 'string' && profile.sub) ||
      (typeof slackUserId === 'string' && slackUserId) ||
      '',
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name: typeof profile.name === 'string' && profile.name ? profile.name : null,
    image: typeof profile.picture === 'string' ? profile.picture : null,
  };
}

/**
 * Normalize a Sign In with LinkedIn callback (OLO-9.18): prefer the id-token claims; fall back to
 * LinkedIn's OIDC userinfo resource when the id token is absent. The claims pass through
 * untouched, so `resolveOAuthEmailVerified` honors `email_verified` only when LinkedIn sends it as
 * true; an absent or false claim fail-closes to link-first. The identity is keyed on `sub`, the
 * member identifier LinkedIn issues to this application.
 *
 * @param tokens The tokens from the code exchange (`idToken`, then `accessToken`, are read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine; empty (no account id, no email) when
 *   neither source yields claims, which the engine refuses.
 */
async function normalizeLinkedin(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  let claims = decodeJwtClaims(tokens.idToken);
  if (!claims && tokens.accessToken) {
    const body = await fetchJsonWithToken(LINKEDIN_USERINFO_URL, tokens.accessToken, fetchImpl);
    if (body && typeof body === 'object') claims = body as Record<string, unknown>;
  }
  const profile = claims ?? {};
  return {
    accountId: typeof profile.sub === 'string' ? profile.sub : '',
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name: typeof profile.name === 'string' && profile.name ? profile.name : null,
    image: typeof profile.picture === 'string' ? profile.picture : null,
  };
}

/**
 * Build a Discord user's avatar URL the way Better Auth's `discord` provider does: the uploaded
 * avatar (`a_`-prefixed hashes are animated, so `.gif`) or, when none is set, one of Discord's
 * default avatars — indexed by the user id for the current username system (discriminator `0`)
 * and by the discriminator for legacy accounts.
 *
 * @param profile The `/users/@me` body.
 * @returns The avatar URL, or null when the profile has no usable id.
 */
function discordAvatarUrl(profile: Record<string, unknown>): string | null {
  const id = typeof profile.id === 'string' ? profile.id : '';
  if (!/^\d+$/.test(id)) return null;
  if (typeof profile.avatar === 'string' && profile.avatar) {
    const format = profile.avatar.startsWith('a_') ? 'gif' : 'png';
    return `${DISCORD_CDN_URL}/avatars/${id}/${profile.avatar}.${format}`;
  }
  const discriminator = typeof profile.discriminator === 'string' ? profile.discriminator : '0';
  const legacyIndex = Number.parseInt(discriminator, 10) % 5;
  const index =
    discriminator === '0' || Number.isNaN(legacyIndex)
      ? Number((BigInt(id) >> BigInt(22)) % BigInt(6))
      : legacyIndex;
  return `${DISCORD_CDN_URL}/embed/avatars/${index}.png`;
}

/**
 * Normalize a Discord sign-in (OLO-9.19): fetch `/users/@me` with the access token and map `id`
 * / `email` / `global_name` / avatar. Discord reports whether the account's email is verified as
 * the boolean `verified`; it is stamped onto the profile as `email_verified` — true only when
 * `verified` is exactly `true` — so `resolveOAuthEmailVerified` refuses an unverified address
 * (`unverified-email`). Any `email_verified` field in the body itself is overwritten, never
 * trusted. The identity is keyed on the user id (a snowflake); the mutable `username` is never
 * the key. A failed fetch yields an empty profile (no account id, no email), which the engine
 * refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeDiscord(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(DISCORD_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const profile: Record<string, unknown> =
    body && typeof body === 'object' ? { ...(body as object) } : {};
  profile.email_verified = profile.verified === true;
  return {
    accountId: typeof profile.id === 'string' ? profile.id : '',
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name:
      (typeof profile.global_name === 'string' && profile.global_name) ||
      (typeof profile.username === 'string' && profile.username) ||
      null,
    image: discordAvatarUrl(profile),
  };
}

/**
 * Normalize a Salesforce sign-in (OLO-9.20): prefer the id-token claims; when they carry no
 * `email` (Salesforce puts the standard claims on the id token only when the app is configured
 * to), read the OIDC userinfo resource under the configured issuer instead. The claims pass
 * through untouched, so `resolveOAuthEmailVerified` honors `email_verified` only when Salesforce
 * sends it as true; an absent or false claim fail-closes to link-first.
 *
 * The identity is keyed on `sub` — the user's identity URL, which names the org and the user. A
 * userinfo body whose `sub` differs from the id token's is discarded (OIDC Core §5.3.2): it does
 * not describe the person who signed in.
 *
 * @param tokens The tokens from the code exchange (`idToken`, then `accessToken`, are read).
 * @param env Resolved environment (`SALESFORCE_ISSUER` selects the userinfo host).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine; empty (no account id, no email) when
 *   neither source yields claims, which the engine refuses.
 */
async function normalizeSalesforce(
  tokens: OAuth2Tokens,
  env: Record<string, string | undefined>,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  let profile: Record<string, unknown> = decodeJwtClaims(tokens.idToken) ?? {};
  if (typeof profile.email !== 'string' && tokens.accessToken) {
    const body = await fetchJsonWithToken(salesforceUserInfoUrl(env), tokens.accessToken, fetchImpl);
    if (body && typeof body === 'object') {
      const userInfo = body as Record<string, unknown>;
      const idTokenSub = typeof profile.sub === 'string' ? profile.sub : null;
      if (!idTokenSub || userInfo.sub === idTokenSub) profile = userInfo;
    }
  }
  return {
    accountId: typeof profile.sub === 'string' ? profile.sub : '',
    profile,
    email: typeof profile.email === 'string' ? profile.email : null,
    name: typeof profile.name === 'string' && profile.name ? profile.name : null,
    image: typeof profile.picture === 'string' ? profile.picture : null,
  };
}

/**
 * Read a Notion **person** user object, or null when the value is not one. A bot owner, a
 * workspace-level owner (`{ workspace: true }`) and a user object without an id are all refused:
 * only a person can sign in.
 *
 * @param value A candidate Notion user object (the token response's `owner.user`, or
 *   `bot.owner.user` from `/v1/users/me`).
 * @returns The user object, or null.
 */
function readNotionPerson(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') return null;
  const user = value as Record<string, unknown>;
  if (typeof user.id !== 'string' || !user.id) return null;
  return user.type === 'person' ? user : null;
}

/**
 * The email address of a Notion person (`person.email`), or null when Notion shared none.
 *
 * @param user A Notion user object.
 * @returns The address, or null.
 */
function notionPersonEmail(user: Record<string, unknown>): string | null {
  const person = user.person;
  if (!person || typeof person !== 'object') return null;
  const email = (person as Record<string, unknown>).email;
  return typeof email === 'string' && email ? email : null;
}

/**
 * Normalize a Notion sign-in (OLO-9.21). The person who authorized the integration is its
 * **owner user**: Notion returns it with the code exchange (`owner.user` on the token response,
 * kept on `tokens.raw`), and again as `bot.owner.user` from `/v1/users/me` — the resource Better
 * Auth's `notion()` helper reads. The token response is used when it names a person and an email;
 * otherwise (a partial user object, or a custom exchange that kept no raw response) `/v1/users/me`
 * is fetched with the access token.
 *
 * Notion asserts **nothing** about whether that email is verified (Better Auth hard-codes
 * `emailVerified: false`), so the profile never carries `email_verified` — any such field in a
 * Notion body is dropped, not trusted — and `resolveOAuthEmailVerified` fail-closes to link-first:
 * the address can neither join nor create an account. The identity is keyed on the user id (a
 * UUID). A failed fetch, a bot owner or a workspace-level token yields an empty profile (no
 * account id, no email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (`raw.owner` and `accessToken` are read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeNotion(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const raw = tokens.raw && typeof tokens.raw === 'object' ? tokens.raw : {};
  const owner =
    raw.owner && typeof raw.owner === 'object' ? (raw.owner as Record<string, unknown>) : {};
  let user = readNotionPerson(owner.user);
  if ((!user || !notionPersonEmail(user)) && tokens.accessToken) {
    const body = await fetchJsonWithToken(NOTION_USERINFO_URL, tokens.accessToken, fetchImpl, {
      'Notion-Version': NOTION_API_VERSION,
    });
    const bot =
      body && typeof body === 'object' ? (body as Record<string, unknown>).bot : undefined;
    const botOwner =
      bot && typeof bot === 'object' ? (bot as Record<string, unknown>).owner : undefined;
    const fetched = readNotionPerson(
      botOwner && typeof botOwner === 'object'
        ? (botOwner as Record<string, unknown>).user
        : undefined
    );
    // Never swap in a different person than the one the code exchange named.
    if (fetched && (!user || fetched.id === user.id)) user = fetched;
  }
  const profile: Record<string, unknown> = user ? { ...user } : {};
  delete profile.email_verified;
  const email = user ? notionPersonEmail(user) : null;
  if (email) profile.email = email;
  return {
    accountId: typeof profile.id === 'string' ? profile.id : '',
    profile,
    email,
    name: typeof profile.name === 'string' && profile.name ? profile.name : null,
    image: typeof profile.avatar_url === 'string' && profile.avatar_url ? profile.avatar_url : null,
  };
}

/**
 * Normalize a Figma sign-in (OLO-9.22): fetch `/v1/me` with the access token and map `id` /
 * `email` / `handle` / `img_url` — the resource and mapping of Better Auth's `figma()` helper.
 *
 * Figma asserts **nothing** about whether that email is verified (Better Auth hard-codes
 * `emailVerified: false`), so the profile never carries `email_verified` — any such field in a
 * Figma body is dropped, not trusted — and `resolveOAuthEmailVerified` fail-closes to link-first:
 * the address can neither join nor create an account. The identity is keyed on the user id; the
 * mutable `handle` is never the key. A failed fetch yields an empty profile (no account id, no
 * email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeFigma(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(FIGMA_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const profile: Record<string, unknown> =
    body && typeof body === 'object' ? { ...(body as object) } : {};
  delete profile.email_verified;
  return {
    accountId: typeof profile.id === 'string' ? profile.id : '',
    profile,
    email: typeof profile.email === 'string' && profile.email ? profile.email : null,
    name: typeof profile.handle === 'string' && profile.handle ? profile.handle : null,
    image: typeof profile.img_url === 'string' && profile.img_url ? profile.img_url : null,
  };
}

/**
 * Fetch the Linear `viewer` (OLO-9.23): POST the GraphQL query with the access token, matching
 * Better Auth's `linear()` helper. Fail-soft to null on a transport or parse error, a non-2xx
 * response, or a body without a `data.viewer` object (a GraphQL error answers 200 with `errors`).
 *
 * @param accessToken The Linear access token from the code exchange.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The `viewer` object, or null when Linear returned none.
 */
async function fetchLinearViewer(
  accessToken: string,
  fetchImpl: FetchLike
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetchImpl(LINEAR_GRAPHQL_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'User-Agent': 'apiome',
      },
      body: JSON.stringify({ query: LINEAR_VIEWER_QUERY }),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { data?: { viewer?: unknown } } | null;
    const viewer = body && typeof body === 'object' ? body.data?.viewer : null;
    return viewer && typeof viewer === 'object' ? (viewer as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * Normalize a Linear sign-in (OLO-9.23): fetch the GraphQL `viewer` with the access token and map
 * `id` / `email` / `name` / `avatarUrl` — the resource and mapping of Better Auth's `linear()`
 * helper.
 *
 * Linear asserts **nothing** about whether that email is verified (Better Auth hard-codes
 * `emailVerified: false`), so the profile never carries `email_verified` — any such field in a
 * Linear body is dropped, not trusted — and `resolveOAuthEmailVerified` fail-closes to
 * link-first: the address can neither join nor create an account. The identity is keyed on the
 * user id; the mutable name is never the key. A failed fetch yields an empty profile (no account
 * id, no email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeLinear(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const viewer = accessToken ? await fetchLinearViewer(accessToken, fetchImpl) : null;
  const profile: Record<string, unknown> = viewer ? { ...viewer } : {};
  delete profile.email_verified;
  return {
    accountId: typeof profile.id === 'string' ? profile.id : '',
    profile,
    email: typeof profile.email === 'string' && profile.email ? profile.email : null,
    name: typeof profile.name === 'string' && profile.name ? profile.name : null,
    image: typeof profile.avatarUrl === 'string' && profile.avatarUrl ? profile.avatarUrl : null,
  };
}

/**
 * Fetch the signed-in Dropbox account (OLO-9.24): POST `get_current_account` with the access
 * token and **no body**, matching Better Auth's `dropbox()` helper. No `Content-Type` is sent —
 * Dropbox rejects an empty body declared as JSON. Fail-soft to null on a transport or parse
 * error, a non-2xx response, or a body that is not an object.
 *
 * @param accessToken The Dropbox access token from the code exchange.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The account object, or null when Dropbox returned none.
 */
async function fetchDropboxAccount(
  accessToken: string,
  fetchImpl: FetchLike
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetchImpl(DROPBOX_USERINFO_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/json',
        'User-Agent': 'apiome',
      },
    });
    if (!res.ok) return null;
    const body = await res.json();
    return body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/**
 * Normalize a Dropbox sign-in (OLO-9.24): fetch `get_current_account` with the access token and
 * map `account_id` / `email` / `name.display_name` / `profile_photo_url` — the resource and
 * mapping of Better Auth's `dropbox()` helper.
 *
 * Dropbox reports whether the account's email is verified as the boolean `email_verified`. It is
 * re-stamped onto the profile fail-closed — true only when the field is exactly `true` — so a
 * missing, null or non-boolean value (the string `"true"`, the number `1`) is unverified and
 * `resolveOAuthEmailVerified` refuses the address (`unverified-email`). The identity is keyed on
 * the account id (`dbid:…`); the mutable display name is never the key. A failed fetch yields an
 * empty profile (no account id, no email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeDropbox(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const account = accessToken ? await fetchDropboxAccount(accessToken, fetchImpl) : null;
  const profile: Record<string, unknown> = account ? { ...account } : {};
  profile.email_verified = profile.email_verified === true;
  const names =
    profile.name && typeof profile.name === 'object'
      ? (profile.name as Record<string, unknown>)
      : {};
  return {
    accountId: typeof profile.account_id === 'string' ? profile.account_id : '',
    profile,
    email: typeof profile.email === 'string' && profile.email ? profile.email : null,
    name: typeof names.display_name === 'string' && names.display_name ? names.display_name : null,
    image:
      typeof profile.profile_photo_url === 'string' && profile.profile_photo_url
        ? profile.profile_photo_url
        : null,
  };
}

/**
 * Normalize a Zoom sign-in (OLO-9.25): fetch `/v2/users/me` with the access token and map `id` /
 * `email` / `display_name` / `pic_url` — the resource and mapping of Better Auth's `zoom()`
 * helper.
 *
 * Zoom reports whether the account's email is verified as the integer `verified` (`1` verified,
 * `0` not). It is normalized onto the profile as the boolean `email_verified`, fail-closed: true
 * only when `verified` is exactly the number `1` — Better Auth's `Boolean(verified)` would also
 * accept `2`, `"0"` or `"false"`. A missing, null, boolean or string value is unverified, any
 * `email_verified` field in the Zoom body is overwritten, never trusted, and
 * `resolveOAuthEmailVerified` then refuses the address (`unverified-email`). The identity is keyed
 * on the user id; the mutable display name is never the key. A failed fetch, or a body whose `id`
 * is not a non-empty string, yields an empty profile (no account id, no email), which the engine
 * refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeZoom(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(ZOOM_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const user =
    body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : {};
  // A body without a string user id is no identity at all: drop it whole, so the engine cannot
  // fall back to keying on a malformed `id` (or a stray `sub`) from the raw profile.
  const accountId = typeof user.id === 'string' ? user.id : '';
  const profile: Record<string, unknown> = accountId ? { ...user } : {};
  profile.email_verified = profile.verified === 1;
  return {
    accountId,
    profile,
    email: typeof profile.email === 'string' && profile.email ? profile.email : null,
    name:
      typeof profile.display_name === 'string' && profile.display_name
        ? profile.display_name
        : null,
    image: typeof profile.pic_url === 'string' && profile.pic_url ? profile.pic_url : null,
  };
}

/**
 * Normalize a Sign in with Hugging Face callback (OLO-9.26): fetch the OIDC userinfo resource
 * with the access token and map `sub` / `email` / `name` / `picture` — the resource and mapping
 * of Better Auth's `huggingface()` helper. The display name falls back to `preferred_username`
 * (the Hugging Face username) when the account has no full name.
 *
 * The claims pass through untouched, so `resolveOAuthEmailVerified` honors `email_verified` only
 * when Hugging Face sends it as true; an absent or false claim fail-closes to link-first
 * (`unverified-email`). The identity is keyed on `sub`, the Hugging Face user id; the mutable
 * username is never the key. A failed fetch, or a body whose `sub` is not a non-empty string,
 * yields an empty profile (no account id, no email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeHuggingface(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(HUGGINGFACE_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const claims =
    body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : {};
  // A body without a string `sub` is no identity at all: drop it whole, so the engine cannot
  // fall back to keying on a malformed `sub` (or a stray `id`) from the raw profile.
  const accountId = typeof claims.sub === 'string' ? claims.sub : '';
  const profile: Record<string, unknown> = accountId ? claims : {};
  const name =
    (typeof profile.name === 'string' && profile.name) ||
    (typeof profile.preferred_username === 'string' && profile.preferred_username) ||
    null;
  return {
    accountId,
    profile,
    email: typeof profile.email === 'string' && profile.email ? profile.email : null,
    name,
    image: typeof profile.picture === 'string' && profile.picture ? profile.picture : null,
  };
}

/**
 * Normalize a Sign in with Vercel callback (OLO-9.27): fetch the userinfo resource with the access
 * token and map `sub` / `email` / `name` / `picture` — the resource and mapping of Better Auth's
 * `vercel()` helper. The display name falls back to `preferred_username` (the Vercel username)
 * when the account has no full name.
 *
 * Vercel's userinfo resource reports whether the email is verified as the boolean
 * `email_verified`. It is re-stamped onto the profile fail-closed: true only when it is exactly
 * `true` — a missing, null, numeric or string value (even `"true"`, which
 * `resolveOAuthEmailVerified` would otherwise accept) is unverified, so the engine refuses the
 * address (`unverified-email`). The identity is keyed on `sub`, the Vercel user id; the mutable
 * username is never the key. A failed fetch, or a body whose `sub` is not a non-empty string,
 * yields an empty profile (no account id, no email), which the engine refuses.
 *
 * @param tokens The tokens from the code exchange (only `accessToken` is read).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The normalized profile for the resolution engine.
 */
async function normalizeVercel(
  tokens: OAuth2Tokens,
  fetchImpl: FetchLike
): Promise<NormalizedOAuthProfile> {
  const accessToken = tokens.accessToken ?? '';
  const body = accessToken
    ? await fetchJsonWithToken(VERCEL_USERINFO_URL, accessToken, fetchImpl)
    : null;
  const claims =
    body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : {};
  // A body without a string `sub` is no identity at all: drop it whole, so the engine cannot
  // fall back to keying on a malformed `sub` (or a stray `id`) from the raw profile.
  const accountId = typeof claims.sub === 'string' ? claims.sub : '';
  const profile: Record<string, unknown> = accountId ? { ...claims } : {};
  profile.email_verified = profile.email_verified === true;
  const name =
    (typeof profile.name === 'string' && profile.name) ||
    (typeof profile.preferred_username === 'string' && profile.preferred_username) ||
    null;
  return {
    accountId,
    profile,
    email: typeof profile.email === 'string' && profile.email ? profile.email : null,
    name,
    image: typeof profile.picture === 'string' && profile.picture ? profile.picture : null,
  };
}

/* ── getUserInfo runner: normalize → resolve → admit or override ────────────────────────────── */

/**
 * Dependencies a provider's `getUserInfo` runner needs, all injectable so the whole flow is testable
 * without a database, network, or request context.
 */
export interface OAuthRunnerDeps {
  /** Persistence for the resolution engine; defaults to the shared production store. */
  store?: ResolutionStore;
  /** Fetch implementation for the GitHub/GitLab userinfo calls; defaults to global fetch. */
  fetchImpl?: FetchLike;
  /**
   * Resolve the "link another provider" session user id from apiome's one-shot link-intent cookie,
   * or null for a normal sign-in. Defaults to {@link resolveLinkIntentUserId}.
   */
  resolveLinkToUserId?: (provider: string) => Promise<string | null>;
  /** Environment to read (injectable for tests; defaults to `process.env`). */
  env?: Record<string, string | undefined>;
}

/** The providers this module builds, mapped to their normalizer. */
const NORMALIZERS: Record<
  string,
  (tokens: OAuth2Tokens, env: Record<string, string | undefined>, fetchImpl: FetchLike) => Promise<NormalizedOAuthProfile> | NormalizedOAuthProfile
> = {
  github: normalizeGithub,
  gitlab: normalizeGitlab,
  google: (tokens, env) => normalizeGoogle(tokens, env),
  azure: (tokens) => normalizeAzure(tokens),
  okta: (tokens) => normalizeOkta(tokens),
  aws: (tokens) => normalizeAws(tokens),
  keycloak: (tokens) => normalizeKeycloak(tokens),
  oidc: (tokens) => normalizeOidc(tokens),
  auth0: (tokens) => normalizeAuth0(tokens),
  line: (tokens, env, fetchImpl) => normalizeLine(tokens, env, fetchImpl),
  vk: (tokens, env, fetchImpl) => normalizeVk(tokens, env, fetchImpl),
  wechat: (tokens, env, fetchImpl) => normalizeWechat(tokens, env, fetchImpl),
  atlassian: (tokens, _env, fetchImpl) => normalizeAtlassian(tokens, fetchImpl),
  bitbucket: (tokens, _env, fetchImpl) => normalizeBitbucket(tokens, fetchImpl),
  slack: (tokens, _env, fetchImpl) => normalizeSlack(tokens, fetchImpl),
  linkedin: (tokens, _env, fetchImpl) => normalizeLinkedin(tokens, fetchImpl),
  discord: (tokens, _env, fetchImpl) => normalizeDiscord(tokens, fetchImpl),
  salesforce: (tokens, env, fetchImpl) => normalizeSalesforce(tokens, env, fetchImpl),
  notion: (tokens, _env, fetchImpl) => normalizeNotion(tokens, fetchImpl),
  figma: (tokens, _env, fetchImpl) => normalizeFigma(tokens, fetchImpl),
  linear: (tokens, _env, fetchImpl) => normalizeLinear(tokens, fetchImpl),
  dropbox: (tokens, _env, fetchImpl) => normalizeDropbox(tokens, fetchImpl),
  zoom: (tokens, _env, fetchImpl) => normalizeZoom(tokens, fetchImpl),
  huggingface: (tokens, _env, fetchImpl) => normalizeHuggingface(tokens, fetchImpl),
  vercel: (tokens, _env, fetchImpl) => normalizeVercel(tokens, fetchImpl),
};

/**
 * Read apiome's one-shot `oauth_link_intent` cookie to decide whether this callback is an explicit
 * "link another provider" action for `provider`. Delegates to the shared link-intent reader
 * (`oauth-link-intent.checkLinkingIntent`) via a lazy import so this module's static graph stays free
 * of `next/headers`. Fail-soft: any error yields null (a normal sign-in).
 *
 * @param provider The provider slug reported by the callback.
 * @returns The session user id to link to, or null.
 */
export async function resolveLinkIntentUserId(provider: string): Promise<string | null> {
  try {
    const { checkLinkingIntent } = await import('./oauth-link-intent');
    const intent = await checkLinkingIntent();
    return intent && intent.provider === provider && intent.userId ? intent.userId : null;
  } catch {
    return null;
  }
}

/**
 * Build the `getUserInfo(tokens)` hook for a provider: normalize the profile, run the shared
 * account-resolution engine, and either admit the sign-in (return the Better Auth user info) or
 * publish the engine's redirect path and return null (Better Auth then redirects, and the handler
 * wrapper rewrites the `Location`).
 *
 * The returned `emailVerified` is computed with the **same** readers the engine uses
 * (`resolveEntraEmailVerified` for azure, `resolveOAuthEmailVerified` otherwise), so Better Auth's
 * own account handling sees the identical verified signal the engine decided over.
 *
 * @param provider The provider slug (github | gitlab | azure | google | okta | aws | keycloak |
 *   oidc | auth0 | line | vk | wechat | atlassian | bitbucket | slack | linkedin |
 *   discord | salesforce | notion | figma | linear | dropbox | zoom | huggingface | vercel).
 * @param deps Injectable dependencies (store, fetch, link-intent resolver, env).
 * @returns A `getUserInfo` function returning the Better Auth user info on admit, or null otherwise.
 */
export function makeOAuthGetUserInfo(
  provider: string,
  deps: OAuthRunnerDeps = {}
): (tokens: OAuth2Tokens) => Promise<OAuth2UserInfo | null> {
  const store = deps.store ?? resolutionStore;
  const fetchImpl = deps.fetchImpl ?? (fetch as unknown as FetchLike);
  const resolveLink = deps.resolveLinkToUserId ?? resolveLinkIntentUserId;
  const envForRun = deps.env ?? process.env;
  const normalize = NORMALIZERS[provider];

  return async (tokens: OAuth2Tokens): Promise<OAuth2UserInfo | null> => {
    if (!normalize) {
      // A provider without a normalizer can never sign in — refuse on the stable code rather than
      // letting Better Auth fall through to its own handling.
      setOauthRedirectOverride(loginErrorRedirect(AUTH_ERROR_CODES.PROVIDER_NOT_CONFIGURED));
      return null;
    }

    let normalized: NormalizedOAuthProfile;
    try {
      normalized = await normalize(tokens, envForRun, fetchImpl);
    } catch (error) {
      // A normalizer only throws for a hard rejection — today the Google Workspace-domain gate
      // (OLO-9.2). Refuse the sign-in with the generic on-contract code so it neither leaks whether
      // the domain matched nor drifts from the error contract.
      console.error(`[betterAuthOAuthProviders] ${provider} profile normalization rejected:`, error);
      setOauthRedirectOverride(loginErrorRedirect(AUTH_ERROR_CODES.SIGN_IN_FAILED));
      return null;
    }

    const linkToUserId = await resolveLink(provider);

    const ctx: BetterAuthOAuthContext = {
      accountId: normalized.accountId || null,
      profile: normalized.profile,
      tokens: {
        accessToken: tokens.accessToken ?? null,
        refreshToken: tokens.refreshToken ?? null,
        accessTokenExpiresAt: tokens.accessTokenExpiresAt ?? null,
      },
    };

    const result: OAuthSignInResult = await resolveBetterAuthOAuthSignIn(
      provider,
      ctx,
      linkToUserId,
      store
    );

    if (result === true) {
      // Admitted: hand Better Auth the resolved user info so it establishes the session. The
      // verified flag is computed exactly as the engine computed it, so Better Auth's own account
      // handling never sees a different signal than the engine decided over.
      const account = { email_verified: normalized.profile.email_verified };
      const emailVerified =
        provider === 'azure'
          ? resolveEntraEmailVerified(normalized.profile, account, canonicalizeEmail(normalized.email))
          : resolveOAuthEmailVerified(normalized.profile, account);

      // Link-only providers (e.g. WeChat) share no email. Better Auth's generic callback requires
      // one to establish the session — prefer the bound apiome user's email so findOAuthUser
      // resolves to the existing account instead of fabricating an orphan.
      let email = normalized.email;
      let name = normalized.name;
      if (!email && normalized.accountId) {
        const bound = await store.getIdentity(provider, normalized.accountId);
        if (bound.found && bound.userId) {
          const user = await store.getUserById(bound.userId);
          if (user?.email) email = user.email;
          if (!name && user?.name) name = user.name;
        }
      }
      if (!email) {
        setOauthRedirectOverride(loginErrorRedirect(AUTH_ERROR_CODES.EMAIL_REQUIRED));
        return null;
      }

      return {
        id: normalized.accountId,
        email,
        emailVerified,
        name: name ?? normalized.accountId,
        image: normalized.image ?? undefined,
      };
    }

    // Any non-admit outcome is either a redirect path (login error, onboarding, or linked-accounts)
    // or a contained `false` (a store/provider fault the engine swallowed rather than admitting).
    // Map the bare `false` to the generic on-contract failure code so a fault never leaks and never
    // falls through to a sign-in. Publish the path and return null so Better Auth aborts before
    // creating any user.
    setOauthRedirectOverride(
      typeof result === 'string' ? result : loginErrorRedirect(AUTH_ERROR_CODES.SIGN_IN_FAILED)
    );
    return null;
  };
}

/* ── Config builder ────────────────────────────────────────────────────────────────────────── */

/**
 * Build one {@link GenericOAuthConfig} for a provider id, or null when the id is not one this
 * module implements. Wires the client credentials (from the resolved env), the endpoint/issuer
 * overrides (OLO-7.4), the scopes and PKCE posture that match the NextAuth providers, and the
 * `getUserInfo` hook that carries verified-email normalization + the `hd` gate + the resolution
 * decision.
 *
 * @param providerId The registry provider slug.
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @param deps Injectable runner dependencies forwarded to {@link makeOAuthGetUserInfo}.
 * @returns The generic-OAuth config, or null for an unknown/unsupported id.
 */
export function buildGenericOAuthConfig(
  providerId: string,
  env: Record<string, string | undefined> = process.env,
  deps: OAuthRunnerDeps = {}
): GenericOAuthConfig | null {
  const runnerDeps: OAuthRunnerDeps = { ...deps, env };
  const getUserInfo = makeOAuthGetUserInfo(providerId, runnerDeps);

  switch (providerId) {
    case 'github': {
      const web = githubOauthWebBaseUrl(env);
      return {
        providerId: 'github',
        clientId: readEnvString(env, 'GITHUB_ID') ?? '',
        clientSecret: readEnvString(env, 'GITHUB_SECRET') ?? '',
        authorizationUrl: `${web}/login/oauth/authorize`,
        tokenUrl: `${web}/login/oauth/access_token`,
        userInfoUrl: `${githubApiBaseUrl(env)}/user`,
        scopes: GITHUB_OAUTH_SCOPE.split(/\s+/).filter(Boolean),
        // GitHub OAuth Apps do not support PKCE; this confidential client authenticates the code
        // exchange with GITHUB_SECRET (state is enforced by Better Auth). Mirrors the NextAuth
        // `checks: ['state']` posture.
        pkce: false,
        getUserInfo,
      };
    }
    case 'gitlab': {
      const base = gitlabBaseUrl(env);
      return {
        providerId: 'gitlab',
        clientId: readEnvString(env, 'GITLAB_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'GITLAB_CLIENT_SECRET') ?? '',
        authorizationUrl: `${base}/oauth/authorize`,
        tokenUrl: `${base}/oauth/token`,
        userInfoUrl: `${base}/api/v4/user`,
        scopes: GITLAB_OAUTH_SCOPE.split(/\s+/).filter(Boolean),
        pkce: true,
        getUserInfo,
      };
    }
    case 'google': {
      return {
        providerId: 'google',
        clientId: readEnvString(env, 'GOOGLE_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'GOOGLE_CLIENT_SECRET') ?? '',
        // Discovery honours the GOOGLE_ISSUER override so the e2e journey can point sign-in at a mock
        // issuer; the authorization/token endpoints come from the discovery document.
        discoveryUrl: `${googleIssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: ['openid', 'email', 'profile'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'azure': {
      const tenant = readEnvString(env, 'AZURE_AD_TENANT') ?? 'common';
      return {
        providerId: 'azure',
        clientId: readEnvString(env, 'AZURE_AD_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'AZURE_AD_CLIENT_SECRET') ?? '',
        // Tenant-scoped OIDC discovery against the Entra authority (overridable via
        // AZURE_AD_AUTHORITY_BASE_URL); `offline_access` makes Microsoft issue a refresh token.
        discoveryUrl: `${entraAuthorityBaseUrl(env)}/${tenant}/v2.0/.well-known/openid-configuration`,
        scopes: ['openid', 'profile', 'email', 'offline_access'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'okta': {
      return {
        providerId: 'okta',
        clientId: readEnvString(env, 'OKTA_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'OKTA_CLIENT_SECRET') ?? '',
        // Org / authorization-server issuer (required via OLO-9.1); discovery supplies authorize/token.
        discoveryUrl: `${oktaIssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: ['openid', 'email', 'profile'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'aws': {
      return {
        providerId: 'aws',
        clientId: readEnvString(env, 'COGNITO_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'COGNITO_CLIENT_SECRET') ?? '',
        // Cognito user-pool issuer (required via OLO-9.1); discovery supplies authorize/token
        // (Hosted UI). Form: https://cognito-idp.<region>.amazonaws.com/<userPoolId>
        discoveryUrl: `${cognitoIssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: ['openid', 'email', 'profile'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'keycloak': {
      return {
        providerId: 'keycloak',
        clientId: readEnvString(env, 'KEYCLOAK_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'KEYCLOAK_CLIENT_SECRET') ?? '',
        // Realm issuer (required via OLO-9.1); discovery supplies authorize/token.
        // Form: https://kc.example.com/realms/<realm>
        discoveryUrl: `${keycloakIssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: ['openid', 'email', 'profile'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'oidc': {
      return {
        providerId: 'oidc',
        clientId: readEnvString(env, 'OIDC_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'OIDC_CLIENT_SECRET') ?? '',
        // Generic IdP issuer (required via OLO-9.1); discovery supplies authorize/token.
        // Optional OIDC_SCOPES overrides the default openid/profile/email trio (OLO-9.6).
        discoveryUrl: `${oidcIssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: oidcScopes(env),
        pkce: true,
        getUserInfo,
      };
    }
    case 'auth0': {
      return {
        providerId: 'auth0',
        clientId: readEnvString(env, 'AUTH0_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'AUTH0_CLIENT_SECRET') ?? '',
        // Tenant issuer (required via OLO-9.1); discovery supplies authorize/token.
        // Form: https://<tenant>.auth0.com
        discoveryUrl: `${auth0IssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: ['openid', 'email', 'profile'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'line': {
      return {
        providerId: 'line',
        clientId: readEnvString(env, 'LINE_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'LINE_CLIENT_SECRET') ?? '',
        // Fixed LINE Login v2.1 endpoints (Better Auth `line()` helper). Email requires an
        // approved channel permission; multi-channel JP/TW/TH use distinct providerIds in docs.
        authorizationUrl: 'https://access.line.me/oauth2/v2.1/authorize',
        tokenUrl: 'https://api.line.me/oauth2/v2.1/token',
        userInfoUrl: LINE_USERINFO_URL,
        scopes: ['openid', 'profile', 'email'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'vk': {
      return {
        providerId: 'vk',
        clientId: readEnvString(env, 'VK_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'VK_CLIENT_SECRET') ?? '',
        // Fixed VK ID endpoints (Better Auth `vk()` helper). Email arrives with the grant but
        // no verified claim → fail-closed link-first. user_info is POST form (see normalizeVk).
        authorizationUrl: VK_AUTHORIZE_URL,
        tokenUrl: VK_TOKEN_URL,
        userInfoUrl: VK_USERINFO_URL,
        scopes: ['email', 'phone'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'wechat': {
      const clientId = readEnvString(env, 'WECHAT_CLIENT_ID') ?? '';
      const lang = readEnvString(env, 'WECHAT_LANG') === 'en' ? 'en' : 'cn';
      return {
        providerId: 'wechat',
        clientId,
        clientSecret: readEnvString(env, 'WECHAT_CLIENT_SECRET') ?? '',
        // QR Website App flow (Better Auth `wechat()`). Hash `#wechat_redirect` is required by
        // WeChat; `appid` (not `client_id`) is the credential param — also set via
        // authorizationUrlParams. Custom getToken performs the GET appid/secret exchange.
        // No email → link-only. Identity prefers unionid over openid (see AUTH_PROVIDER_SETUP.md).
        authorizationUrl: WECHAT_AUTHORIZE_URL,
        tokenUrl: WECHAT_TOKEN_URL,
        userInfoUrl: WECHAT_USERINFO_URL,
        scopes: ['snsapi_login'],
        pkce: false,
        authorizationUrlParams: { appid: clientId, lang },
        getToken: (data) =>
          exchangeWechatAuthorizationCode(
            data,
            env,
            runnerDeps.fetchImpl ?? (fetch as unknown as FetchLike)
          ),
        getUserInfo,
      };
    }
    case 'atlassian': {
      return {
        providerId: 'atlassian',
        clientId: readEnvString(env, 'ATLASSIAN_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'ATLASSIAN_CLIENT_SECRET') ?? '',
        // Fixed Atlassian OAuth 2.0 (3LO) endpoints — no issuer. The profile comes from the User
        // Identity API (`/me`), which needs the `read:me` scope and the `api.atlassian.com`
        // audience; `prompt=consent` is what Atlassian's authorize endpoint expects.
        authorizationUrl: ATLASSIAN_AUTHORIZE_URL,
        tokenUrl: ATLASSIAN_TOKEN_URL,
        userInfoUrl: ATLASSIAN_USERINFO_URL,
        scopes: ['read:me', 'read:account'],
        pkce: true,
        authorizationUrlParams: { audience: ATLASSIAN_AUDIENCE, prompt: 'consent' },
        getUserInfo,
      };
    }
    case 'bitbucket': {
      return {
        providerId: 'bitbucket',
        clientId: readEnvString(env, 'BITBUCKET_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'BITBUCKET_CLIENT_SECRET') ?? '',
        // Fixed Bitbucket Cloud endpoints — no issuer. The `email` scope unlocks
        // `/2.0/user/emails` (see normalizeBitbucket).
        authorizationUrl: BITBUCKET_AUTHORIZE_URL,
        tokenUrl: BITBUCKET_TOKEN_URL,
        userInfoUrl: BITBUCKET_USERINFO_URL,
        scopes: BITBUCKET_OAUTH_SCOPE.split(/\s+/).filter(Boolean),
        // Bitbucket's documented code exchange authenticates the consumer with HTTP Basic
        // (key:secret) and does not document PKCE; like GitHub, this confidential client relies
        // on the secret and Better Auth's `state` check.
        authentication: 'basic',
        pkce: false,
        getUserInfo,
      };
    }
    case 'slack': {
      return {
        providerId: 'slack',
        clientId: readEnvString(env, 'SLACK_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'SLACK_CLIENT_SECRET') ?? '',
        // Sign in with Slack is OpenID Connect on one fixed issuer — no issuer to configure;
        // discovery supplies the authorize/token endpoints. Like Better Auth's `slack()` helper
        // this confidential client sends no PKCE challenge: it authenticates the code exchange
        // with the client secret, and Better Auth enforces `state`.
        discoveryUrl: SLACK_DISCOVERY_URL,
        scopes: ['openid', 'profile', 'email'],
        pkce: false,
        getUserInfo,
      };
    }
    case 'linkedin': {
      return {
        providerId: 'linkedin',
        clientId: readEnvString(env, 'LINKEDIN_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'LINKEDIN_CLIENT_SECRET') ?? '',
        // Sign In with LinkedIn is OpenID Connect on one fixed issuer — no issuer to configure;
        // discovery supplies the authorize/token endpoints. Like Better Auth's `linkedin()` helper
        // this confidential client sends no PKCE challenge (LinkedIn offers PKCE only to native
        // apps, on a separate endpoint): it authenticates the code exchange with the client
        // secret in the request body, and Better Auth enforces `state`.
        discoveryUrl: LINKEDIN_DISCOVERY_URL,
        scopes: ['openid', 'profile', 'email'],
        pkce: false,
        getUserInfo,
      };
    }
    case 'discord': {
      return {
        providerId: 'discord',
        clientId: readEnvString(env, 'DISCORD_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'DISCORD_CLIENT_SECRET') ?? '',
        // Fixed Discord OAuth 2.0 endpoints, mirrored from Better Auth's `discord()` helper — no
        // issuer. `identify` returns the user, `email` adds the address and its `verified` flag
        // (see normalizeDiscord). Like the helper, this confidential client sends no PKCE
        // challenge (it authenticates the code exchange with the client secret, and Better Auth
        // enforces `state`) and asks with `prompt=none`, so a person who has already authorized
        // the application is not shown Discord's consent screen again.
        authorizationUrl: DISCORD_AUTHORIZE_URL,
        tokenUrl: DISCORD_TOKEN_URL,
        userInfoUrl: DISCORD_USERINFO_URL,
        scopes: ['identify', 'email'],
        pkce: false,
        prompt: 'none',
        getUserInfo,
      };
    }
    case 'salesforce': {
      return {
        providerId: 'salesforce',
        clientId: readEnvString(env, 'SALESFORCE_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'SALESFORCE_CLIENT_SECRET') ?? '',
        // Discovery on the configured issuer — login.salesforce.com unless SALESFORCE_ISSUER
        // names a My Domain or a sandbox — supplies authorize/token. PKCE on, as Better Auth's
        // `salesforce()` helper does and as newer Salesforce apps require.
        discoveryUrl: `${salesforceIssuerBaseUrl(env)}/.well-known/openid-configuration`,
        scopes: ['openid', 'email', 'profile'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'notion': {
      return {
        providerId: 'notion',
        clientId: readEnvString(env, 'NOTION_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'NOTION_CLIENT_SECRET') ?? '',
        // Fixed Notion OAuth 2.0 endpoints, mirrored from Better Auth's `notion()` helper — no
        // issuer. Notion has no scopes (an integration's capabilities are set on the integration),
        // `owner=user` asks for a user-level grant so the token names the person who authorized
        // it, and the code exchange authenticates with HTTP Basic. Like the helper, this
        // confidential client sends no PKCE challenge (Better Auth enforces `state`). The owner
        // user's email carries no verified claim → fail-closed link-first (see normalizeNotion).
        authorizationUrl: NOTION_AUTHORIZE_URL,
        tokenUrl: NOTION_TOKEN_URL,
        userInfoUrl: NOTION_USERINFO_URL,
        scopes: [],
        authorizationUrlParams: { owner: 'user' },
        authentication: 'basic',
        pkce: false,
        getUserInfo,
      };
    }
    case 'figma': {
      return {
        providerId: 'figma',
        clientId: readEnvString(env, 'FIGMA_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'FIGMA_CLIENT_SECRET') ?? '',
        // Fixed Figma OAuth 2.0 endpoints, mirrored from Better Auth's `figma()` helper — no
        // issuer. `current_user:read` is the one scope `/v1/me` needs; the code exchange
        // authenticates with HTTP Basic, and the helper requires a PKCE verifier, so PKCE stays
        // on. The `/v1/me` email carries no verified claim → fail-closed link-first (see
        // normalizeFigma).
        authorizationUrl: FIGMA_AUTHORIZE_URL,
        tokenUrl: FIGMA_TOKEN_URL,
        userInfoUrl: FIGMA_USERINFO_URL,
        scopes: ['current_user:read'],
        authentication: 'basic',
        pkce: true,
        getUserInfo,
      };
    }
    case 'linear': {
      return {
        providerId: 'linear',
        clientId: readEnvString(env, 'LINEAR_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'LINEAR_CLIENT_SECRET') ?? '',
        // Fixed Linear OAuth 2.0 endpoints, mirrored from Better Auth's `linear()` helper — no
        // issuer. `read` is the one scope the `viewer` query needs; the code exchange sends the
        // client id and secret in the form body, and like the helper this confidential client
        // sends no PKCE challenge (Better Auth enforces `state`). Linear has no REST userinfo
        // endpoint, so `userInfoUrl` names the GraphQL endpoint the normalizer POSTs to. The
        // viewer email carries no verified claim → fail-closed link-first (see normalizeLinear).
        authorizationUrl: LINEAR_AUTHORIZE_URL,
        tokenUrl: LINEAR_TOKEN_URL,
        userInfoUrl: LINEAR_GRAPHQL_URL,
        scopes: ['read'],
        authentication: 'post',
        pkce: false,
        getUserInfo,
      };
    }
    case 'dropbox': {
      return {
        providerId: 'dropbox',
        clientId: readEnvString(env, 'DROPBOX_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'DROPBOX_CLIENT_SECRET') ?? '',
        // Fixed Dropbox OAuth 2.0 endpoints, mirrored from Better Auth's `dropbox()` helper — no
        // issuer. `account_info.read` is the one scope `get_current_account` needs; the code
        // exchange sends the client id and secret in the form body together with the PKCE
        // verifier (the helper passes one, so PKCE stays on). No `token_access_type` is sent:
        // Apiome keeps no Dropbox token, so the default short-lived grant is enough.
        // `userInfoUrl` names the RPC endpoint the normalizer POSTs to; its `email_verified`
        // flag is honored fail-closed (see normalizeDropbox).
        authorizationUrl: DROPBOX_AUTHORIZE_URL,
        tokenUrl: DROPBOX_TOKEN_URL,
        userInfoUrl: DROPBOX_USERINFO_URL,
        scopes: ['account_info.read'],
        authentication: 'post',
        pkce: true,
        getUserInfo,
      };
    }
    case 'zoom': {
      return {
        providerId: 'zoom',
        clientId: readEnvString(env, 'ZOOM_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'ZOOM_CLIENT_SECRET') ?? '',
        // Fixed Zoom OAuth 2.0 endpoints, mirrored from Better Auth's `zoom()` helper — no
        // issuer. No scope is requested: the helper sends none, because a Zoom app's scopes are
        // chosen on the app (`user:read:user` is the one `/v2/users/me` needs). The code exchange
        // sends the client id and secret in the form body together with the PKCE verifier (the
        // helper's default, so PKCE stays on). The `verified` flag of `/v2/users/me` is
        // normalized fail-closed to `email_verified` (see normalizeZoom).
        authorizationUrl: ZOOM_AUTHORIZE_URL,
        tokenUrl: ZOOM_TOKEN_URL,
        userInfoUrl: ZOOM_USERINFO_URL,
        scopes: [],
        authentication: 'post',
        pkce: true,
        getUserInfo,
      };
    }
    case 'huggingface': {
      return {
        providerId: 'huggingface',
        clientId: readEnvString(env, 'HUGGINGFACE_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'HUGGINGFACE_CLIENT_SECRET') ?? '',
        // Sign in with Hugging Face is OpenID Connect on one fixed issuer — no issuer to
        // configure; discovery supplies the authorize/token endpoints. Like Better Auth's
        // `huggingface()` helper it asks for `openid profile email` and sends a PKCE challenge
        // (discovery advertises `S256`); the code exchange also carries the client secret.
        discoveryUrl: HUGGINGFACE_DISCOVERY_URL,
        scopes: ['openid', 'profile', 'email'],
        pkce: true,
        getUserInfo,
      };
    }
    case 'vercel': {
      return {
        providerId: 'vercel',
        clientId: readEnvString(env, 'VERCEL_CLIENT_ID') ?? '',
        clientSecret: readEnvString(env, 'VERCEL_CLIENT_SECRET') ?? '',
        // Fixed Sign in with Vercel endpoints, mirrored from Better Auth's `vercel()` helper — no
        // issuer. The app's **Manage** page must enable the `email` and `profile` scopes Apiome
        // asks for (Vercel rejects a request for a scope the app does not have). The code
        // exchange sends the client id and secret in the form body together with the PKCE
        // verifier; Vercel requires PKCE (`S256`). The userinfo `email_verified` flag is
        // re-stamped fail-closed (see normalizeVercel).
        authorizationUrl: VERCEL_AUTHORIZE_URL,
        tokenUrl: VERCEL_TOKEN_URL,
        userInfoUrl: VERCEL_USERINFO_URL,
        scopes: ['openid', 'email', 'profile'],
        authentication: 'post',
        pkce: true,
        getUserInfo,
      };
    }
    default:
      return null;
  }
}

/**
 * Build the generic-OAuth config list for this deployment: one entry per **enabled** registry
 * provider, in registry display order. This is the Better Auth analogue of
 * `configuredOAuthProviders` — the registry (`enabledProviders`) is the single source of the enabled
 * set, so unsetting a provider's env vars removes its sign-in route entirely.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @param deps Injectable runner dependencies forwarded to each provider's `getUserInfo`.
 * @returns The `config` array for the `genericOAuth` plugin (empty when no provider is configured).
 */
export function buildGenericOAuthConfigs(
  env: Record<string, string | undefined> = process.env,
  deps: OAuthRunnerDeps = {}
): GenericOAuthConfig[] {
  const configs: GenericOAuthConfig[] = [];
  for (const descriptor of enabledProviders(env)) {
    const config = buildGenericOAuthConfig(descriptor.id, env, deps);
    if (!config) {
      console.error(
        `[betterAuthOAuthProviders] Provider '${descriptor.id}' is enabled by env but has no ` +
          `Better Auth generic-OAuth config; skipping.`
      );
      continue;
    }
    configs.push(config);
  }
  return configs;
}

/**
 * A stable fingerprint of a generic-OAuth config list, used to decide whether a per-request Better
 * Auth instance can be reused or must be rebuilt (OLO-10.8). Two config lists that would drive the
 * OAuth handshake identically produce the same signature; any change an admin makes from the settings
 * screen — enabling/disabling a provider, or changing a client id, secret, endpoint, or scope —
 * produces a different one, so the next sign-in rebuilds against the new config.
 *
 * The digest covers every field Better Auth's `genericOAuth` uses for the authorize/token/user-info
 * exchange but deliberately excludes the `getUserInfo` closure (a function, not serializable, and
 * identical in behaviour across builds). The client secret is folded in via a SHA-256 digest so a
 * rotated secret still forces a rebuild without the plaintext ever living in the cache key.
 *
 * @param configs The generic-OAuth config list from {@link buildGenericOAuthConfigs}.
 * @returns A hex digest that is equal iff the two config lists are handshake-equivalent.
 */
export function providerConfigSignature(configs: GenericOAuthConfig[]): string {
  const material = configs.map((config) => ({
    providerId: config.providerId,
    clientId: config.clientId,
    // Never place the plaintext secret in the signature; a per-secret digest is enough to detect a
    // rotation. An unset secret hashes to a fixed marker so "no secret" differs from any real one.
    clientSecretDigest:
      typeof config.clientSecret === 'string' && config.clientSecret.length > 0
        ? createHash('sha256').update(config.clientSecret).digest('hex')
        : null,
    authorizationUrl: config.authorizationUrl ?? null,
    tokenUrl: config.tokenUrl ?? null,
    userInfoUrl: config.userInfoUrl ?? null,
    discoveryUrl: config.discoveryUrl ?? null,
    scopes: config.scopes ?? null,
    pkce: config.pkce ?? null,
  }));
  return createHash('sha256').update(JSON.stringify(material)).digest('hex');
}
