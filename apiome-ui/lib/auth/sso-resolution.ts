/**
 * Enterprise SSO sign-ins through the account-resolution engine (EID-1.1, #5011).
 *
 * Better Auth's SSO plugin (`@better-auth/sso`) verifies the IdP's answer — the OIDC code exchange
 * and id token, or the SAML response's signature, audience, timestamps and replay — and then hands
 * the identity to Better Auth core (`handleOAuthUserInfo`), which links it to an existing user,
 * creates a user, or signs a known account in, and finally creates a session. Unlike the generic
 * OAuth providers there is no `getUserInfo` hook in that path, so the resolution engine
 * (`account-resolution.ts`) runs in Better Auth's **database hooks**, gated to the SSO callback
 * routes:
 *
 * | Core step | Hook | What runs |
 * | --- | --- | --- |
 * | new email → create user | `user.create.before` | the email's domain must be one the provider verified; the engine's pure decision for a new email (verified email, sign-up policy) — a refusal stops here, before any row is written |
 * | … then its account | `account.create.before` | OIDC id-token check; the engine's `signup` outcome: a pending sign-up for the onboarding wizard, exactly as the OAuth providers do, and the just-inserted user row is removed |
 * | existing user, new SSO identity | `account.create.before` | domain + OIDC id-token check (the engine links at session time) |
 * | every admitted sign-in | `session.create.before` | `resolveOAuthSignIn('sso:<slug>', …)` — sign in a known identity or auto-link a verified email (writing the `external_auth_providers` binding), refusing disabled / unverified / suspended accounts and identities bound to someone else |
 *
 * A refusal publishes the engine's redirect (`/login?error=<code>`, or the wizard) through the
 * per-request override the OAuth providers already use (`better-auth-oauth-providers.ts`) and
 * throws, so core aborts and the handler retargets the redirect.
 *
 * **Trust.** OIDC: the id token is verified here against the provider's JWKS (issuer + audience)
 * and must carry `email_verified: true`; SAML: the email comes from the provider's configured source
 * (NameID or one attribute) and is trusted only because its domain is one an installation admin
 * verified for that provider. Either way an email outside the provider's verified domains is refused
 * (`sso-email-domain-mismatch`) — an IdP cannot sign in addresses it does not own.
 *
 * Every attempt — admitted or refused — is appended to `auth_events` with `provider = sso:<slug>`
 * through REST's service-token-gated write path (`/v1/internal/auth-events`), best-effort.
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import { randomBytes } from 'node:crypto';
import { APIError } from 'better-auth/api';
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from 'jose';

import {
  AUTH_ERROR_CODES,
  canonicalizeEmail,
  loginErrorRedirect,
  resolveAccountDecision,
  resolveOAuthSignIn,
  type AuthErrorCode,
  type OAuthSignInResult,
  type ResolutionStore,
} from './account-resolution';
import { getOauthRedirectOverride, setOauthRedirectOverride } from './better-auth-oauth-providers';
import { resolutionStore } from './resolution-store';
import { signupPolicyFromEnv } from './signup-policy';
import {
  findSsoProvider,
  NO_SSO_PROVIDERS,
  SSO_CALLBACK_PREFIXES,
  SSO_PLUGIN_PROVIDER_PREFIX,
  type ResolvedSsoProvider,
  type ResolvedSsoProviders,
} from './sso-provider-resolver';
import { REST_API_BASE_URL } from '../rest-auth';

// eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS pool singleton
const connectionPool = require('../db/db') as {
  query: (sql: string, params?: unknown[]) => Promise<{ rows: Record<string, unknown>[]; rowCount?: number | null }>;
};

/* ── Codes ─────────────────────────────────────────────────────────────────────────────────── */

/**
 * Stable codes for SSO refusals the engine does not own. The login page maps each to copy
 * (`src/app/login/auth-error-copy.ts`); `apiome-ui/docs/AUTH_ERROR_CODES.md` documents them.
 */
export const SSO_ERROR_CODES = {
  /** The id token failed verification (signature, issuer or audience) or was missing. */
  TOKEN_INVALID: 'sso-token-invalid',
  /** The SAML response failed validation (signature, audience, timestamps or shape). */
  ASSERTION_INVALID: 'sso-assertion-invalid',
  /** The SAML assertion had already been used. */
  ASSERTION_REPLAYED: 'sso-assertion-replayed',
  /** The IdP answered over a binding apiome does not accept (HTTP-Artifact). */
  BINDING_UNSUPPORTED: 'sso-binding-unsupported',
  /** The OIDC discovery document could not be read at sign-in. */
  DISCOVERY_FAILED: 'sso-discovery-failed',
  /** The sign-in's state was missing, expired or did not match. */
  STATE_INVALID: 'sso-state-invalid',
  /** No enabled provider covers that email domain (or the provider was removed mid sign-in). */
  PROVIDER_NOT_FOUND: 'sso-provider-not-found',
  /** The IdP asserted an email outside the domains verified for it. */
  EMAIL_DOMAIN_MISMATCH: 'sso-email-domain-mismatch',
  /** The account exists but could not be linked to this IdP. */
  ACCOUNT_NOT_LINKED: 'sso-account-not-linked',
} as const;

export type SsoErrorCode = (typeof SSO_ERROR_CODES)[keyof typeof SSO_ERROR_CODES];

/* ── Paths ─────────────────────────────────────────────────────────────────────────────────── */

export { SSO_CALLBACK_PREFIXES };

/** The subset of a Better Auth endpoint context these hooks read. */
export interface SsoHookContext {
  path?: string;
  params?: Record<string, unknown>;
  request?: Request;
  headers?: Headers;
}

/**
 * Whether a Better Auth path is an SSO callback, as a template (`/sso/callback/:providerId`) or a
 * concrete path (`/sso/callback/sso-acme`).
 *
 * @param path The endpoint path.
 * @returns True for an SSO sign-in completion route.
 */
export function isSsoCallbackPath(path: unknown): boolean {
  return typeof path === 'string' && SSO_CALLBACK_PREFIXES.some((prefix) => path.startsWith(prefix));
}

/**
 * The plugin provider id (`sso-<slug>`) an SSO callback is for, or null for any other request.
 *
 * @param ctx The hook's endpoint context (may be absent for internal adapter calls).
 * @returns `sso-<slug>`, or null.
 */
export function ssoProviderIdFromContext(ctx: SsoHookContext | null | undefined): string | null {
  if (!ctx || !isSsoCallbackPath(ctx.path)) return null;
  const param = ctx.params?.providerId;
  if (typeof param === 'string' && param.startsWith(SSO_PLUGIN_PROVIDER_PREFIX)) return param;
  const path = ctx.path as string;
  for (const prefix of SSO_CALLBACK_PREFIXES) {
    if (path.startsWith(prefix)) {
      const segment = decodeURIComponent(path.slice(prefix.length).split(/[/?#]/, 1)[0] ?? '');
      if (segment.startsWith(SSO_PLUGIN_PROVIDER_PREFIX)) return segment;
    }
  }
  return null;
}

/* ── Request scope ─────────────────────────────────────────────────────────────────────────── */

/** What one SSO callback request carries between its hooks. */
interface SsoRequestState {
  /** The routable set this request's auth instance was built from. */
  resolved: ResolvedSsoProviders;
  /** Set by `user.create.before` when core is creating a brand-new user for this sign-in. */
  newUser: { email: string; name: string; passwordMarker: string } | null;
}

const ssoRequestStore = new AsyncLocalStorage<SsoRequestState>();

/**
 * Run one `/api/auth/*` request with the routable SSO set its hooks will consult.
 *
 * @param resolved The routable providers the request's instance was built from.
 * @param fn The request handler.
 * @returns Whatever `fn` returns.
 */
export function runWithSsoRequest<T>(resolved: ResolvedSsoProviders, fn: () => Promise<T>): Promise<T> {
  return ssoRequestStore.run({ resolved, newUser: null }, fn);
}

function currentState(): SsoRequestState {
  return ssoRequestStore.getStore() ?? { resolved: NO_SSO_PROVIDERS, newUser: null };
}

/* ── Dependencies (injectable for tests) ───────────────────────────────────────────────────── */

/** One `auth_events` row, as `/v1/internal/auth-events` accepts it. */
export interface SsoAuthEvent {
  event_type: 'sign_in' | 'sign_up' | 'link';
  outcome: 'success' | 'failure';
  provider: string;
  user_id?: string | null;
  user_label?: string | null;
  error_code?: string | null;
  ip?: string | null;
  user_agent?: string | null;
  detail?: Record<string, unknown>;
}

/** Everything the hooks touch outside this module. */
export interface SsoResolutionDeps {
  store: ResolutionStore;
  /** Verify an OIDC id token for a provider; resolves the claims or throws. */
  verifyIdToken: (provider: ResolvedSsoProvider, idToken: string) => Promise<JWTPayload>;
  /** Hard-delete the throwaway user row core just inserted (matched on id *and* marker). */
  discardNewUser: (userId: string, passwordMarker: string) => Promise<void>;
  /** The `accountId` of a user's account for a plugin provider id. */
  accountIdFor: (userId: string, pluginProviderId: string) => Promise<string | null>;
  /** Append an `auth_events` row (best-effort; never throws). */
  recordEvent: (event: SsoAuthEvent) => Promise<void>;
}

const jwksByUri = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

/**
 * Verify an id token against the provider's JWKS, issuer and audience (the OIDC client id).
 *
 * @param provider The routable provider.
 * @param idToken The compact JWS.
 * @returns The verified claims.
 * @throws When the provider has no JWKS or the token fails verification.
 */
export async function verifyProviderIdToken(provider: ResolvedSsoProvider, idToken: string): Promise<JWTPayload> {
  const config = provider.oidcConfig ?? {};
  const jwksUri = typeof config.jwks_uri === 'string' ? config.jwks_uri : '';
  const clientId = typeof config.client_id === 'string' ? config.client_id : '';
  if (!jwksUri || !clientId) throw new Error('provider has no JWKS or client id');
  let jwks = jwksByUri.get(jwksUri);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(jwksUri));
    jwksByUri.set(jwksUri, jwks);
  }
  const issuer = provider.issuer.replace(/\/+$/, '');
  const { payload } = await jwtVerify(idToken, jwks, { issuer: [issuer, `${issuer}/`], audience: clientId });
  return payload;
}

/** The internal REST write path for `auth_events`. */
async function postAuthEvent(event: SsoAuthEvent): Promise<void> {
  const token = process.env.INTERNAL_SERVICE_TOKEN?.trim();
  if (!token) return;
  const base = process.env.REST_API_BASE_URL?.trim().replace(/\/+$/, '') || REST_API_BASE_URL;
  try {
    await fetch(`${base}/internal/auth-events`, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Service-Token': token },
      body: JSON.stringify(event),
      signal: AbortSignal.timeout(2_000),
    });
  } catch {
    // Best-effort: an audit write never fails the sign-in it records.
  }
}

/** Production dependencies. */
export const defaultSsoResolutionDeps: SsoResolutionDeps = {
  store: resolutionStore,
  verifyIdToken: verifyProviderIdToken,
  discardNewUser: async (userId, passwordMarker) => {
    await connectionPool.query('DELETE FROM apiome.users WHERE id = $1 AND password = $2', [userId, passwordMarker]);
  },
  accountIdFor: async (userId, pluginProviderId) => {
    const result = await connectionPool.query(
      'SELECT "accountId" FROM apiome.account WHERE "userId" = $1 AND "providerId" = $2 ORDER BY "createdAt" DESC LIMIT 1',
      [userId, pluginProviderId]
    );
    const value = result.rows[0]?.accountId;
    return typeof value === 'string' ? value : null;
  },
  recordEvent: postAuthEvent,
};

/* ── Helpers ───────────────────────────────────────────────────────────────────────────────── */

/**
 * Whether an email's domain is one the provider verified (exact match, case-insensitive).
 *
 * @param email The asserted email.
 * @param provider The routable provider.
 * @returns True when the domain is covered.
 */
export function emailInProviderDomains(email: string | null | undefined, provider: ResolvedSsoProvider): boolean {
  const canonical = canonicalizeEmail(email);
  if (!canonical || !canonical.includes('@')) return false;
  const domain = canonical.slice(canonical.lastIndexOf('@') + 1);
  return provider.domains.includes(domain);
}

/** Request IP / UA for the audit row (hashed by REST, never stored raw). */
function clientDetails(ctx: SsoHookContext | null | undefined): { ip: string | null; user_agent: string | null } {
  const headers = ctx?.headers ?? ctx?.request?.headers;
  const forwarded = headers?.get('x-forwarded-for')?.split(',')[0]?.trim() || headers?.get('x-real-ip') || null;
  return { ip: forwarded, user_agent: headers?.get('user-agent') ?? null };
}

/**
 * Refuse the sign-in: publish the redirect, record the failure, and throw so core aborts.
 *
 * @throws Always — an `APIError` carrying the code.
 */
async function refuse(
  deps: SsoResolutionDeps,
  provider: ResolvedSsoProvider | null,
  ctx: SsoHookContext | null | undefined,
  code: AuthErrorCode | SsoErrorCode,
  facts: { email?: string | null; userId?: string | null; eventType?: SsoAuthEvent['event_type'] } = {}
): Promise<never> {
  setOauthRedirectOverride(loginErrorRedirect(code as AuthErrorCode));
  await deps.recordEvent({
    event_type: facts.eventType ?? 'sign_in',
    outcome: 'failure',
    provider: provider?.identityKind ?? 'sso:unknown',
    user_id: facts.userId ?? null,
    user_label: facts.email ?? null,
    error_code: code,
    ...clientDetails(ctx),
    detail: { protocol: provider?.protocol ?? null },
  });
  throw new APIError('FORBIDDEN', { code, message: code });
}

/** The provider an SSO hook is for, or null when the request is not an SSO callback. */
function providerFor(ctx: SsoHookContext | null | undefined): { id: string; provider: ResolvedSsoProvider | null } | null {
  const id = ssoProviderIdFromContext(ctx);
  if (!id) return null;
  return { id, provider: findSsoProvider(currentState().resolved, id) };
}

/** The OIDC id-token check shared by both account paths. */
async function checkOidcIdToken(
  deps: SsoResolutionDeps,
  provider: ResolvedSsoProvider,
  ctx: SsoHookContext | null | undefined,
  idToken: unknown,
  email: string
): Promise<void> {
  if (provider.protocol !== 'oidc') return;
  if (typeof idToken !== 'string' || !idToken) {
    await refuse(deps, provider, ctx, SSO_ERROR_CODES.TOKEN_INVALID, { email });
  }
  let claims: JWTPayload;
  try {
    claims = await deps.verifyIdToken(provider, idToken as string);
  } catch {
    return refuse(deps, provider, ctx, SSO_ERROR_CODES.TOKEN_INVALID, { email });
  }
  const verified = claims.email_verified === true || claims.email_verified === 'true';
  if (!verified) await refuse(deps, provider, ctx, AUTH_ERROR_CODES.UNVERIFIED_EMAIL, { email });
  const claimed = canonicalizeEmail(claims.email);
  if (claimed && claimed !== canonicalizeEmail(email)) {
    await refuse(deps, provider, ctx, SSO_ERROR_CODES.TOKEN_INVALID, { email });
  }
}

/* ── Hooks ─────────────────────────────────────────────────────────────────────────────────── */

/** A user row as `user.create.before` receives it. */
type NewUserData = Record<string, unknown> & { email?: string; name?: string; emailVerified?: boolean };

/**
 * `databaseHooks.user.create.before`: core is about to create a user for an SSO sign-in.
 *
 * Refuses — before any row is written — an email outside the provider's verified domains, an
 * OIDC email the IdP did not mark verified, and an address the sign-up policy refuses. An admitted
 * new user is let through with a throwaway password (the column is NOT NULL) so that
 * `account.create.before`, which has the provider's account id, can turn it into a pending sign-up.
 *
 * @param user The user core is about to insert.
 * @param ctx The endpoint context.
 * @param deps Injectable dependencies.
 * @returns `{ data }` with the throwaway password, or undefined for non-SSO requests.
 */
export async function ssoUserCreateBefore(
  user: NewUserData,
  ctx: SsoHookContext | null | undefined,
  deps: SsoResolutionDeps = defaultSsoResolutionDeps
): Promise<{ data: NewUserData } | undefined> {
  const found = providerFor(ctx);
  if (!found) return undefined;
  const { provider } = found;
  const email = canonicalizeEmail(user.email);
  if (!provider) return refuse(deps, null, ctx, SSO_ERROR_CODES.PROVIDER_NOT_FOUND, { email, eventType: 'sign_up' });
  if (!email) return refuse(deps, provider, ctx, AUTH_ERROR_CODES.EMAIL_REQUIRED, { eventType: 'sign_up' });
  if (!emailInProviderDomains(email, provider)) {
    return refuse(deps, provider, ctx, SSO_ERROR_CODES.EMAIL_DOMAIN_MISMATCH, { email, eventType: 'sign_up' });
  }
  // OIDC: the plugin reports the IdP's `email_verified` (trustEmailVerified — safe because only
  // admins register providers); SAML: the verified domain is the proof.
  const emailVerified = provider.protocol === 'saml' ? true : user.emailVerified === true;
  const decision = resolveAccountDecision({
    provider: provider.identityKind,
    providerUserId: 'pending', // the account id arrives in account.create.before
    email,
    emailVerified,
    linkToUserId: null,
    identity: { found: false, user: null },
    emailUser: null, // core only creates a user when none has this email
    signupPolicy: (await deps.store.getSignupPolicy?.()) ?? signupPolicyFromEnv(),
  });
  if (decision.action !== 'signup') {
    const code = decision.action === 'reject' ? decision.code : AUTH_ERROR_CODES.SIGN_IN_FAILED;
    return refuse(deps, provider, ctx, code, { email, eventType: 'sign_up' });
  }
  const passwordMarker = `sso-pending-${randomBytes(24).toString('hex')}`;
  const name = (typeof user.name === 'string' && user.name.trim()) || email.split('@')[0];
  const state = ssoRequestStore.getStore();
  if (state) state.newUser = { email, name, passwordMarker };
  return { data: { ...user, email, name, emailVerified: true, password: passwordMarker } };
}

/** An account row as `account.create.before` receives it. */
type NewAccountData = Record<string, unknown> & {
  userId?: string;
  accountId?: string;
  providerId?: string;
  idToken?: string | null;
  accessToken?: string | null;
};

/**
 * `databaseHooks.account.create.before`: core is attaching an SSO identity to a user.
 *
 * For a **brand-new user** (flagged by {@link ssoUserCreateBefore}) the engine's `signup` outcome
 * runs exactly as for the OAuth providers: a pending sign-up row keyed on the provider's account id,
 * and a redirect to the onboarding wizard (`/signup/oauth?token=…`). The throwaway user row core
 * inserted a moment ago is removed and core is stopped, so the wizard creates the real account.
 *
 * For an **existing user** it checks the email's domain and, for OIDC, the id token; the engine
 * itself runs at session creation.
 *
 * @param account The account core is about to insert.
 * @param ctx The endpoint context.
 * @param deps Injectable dependencies.
 * @returns undefined (admit) — refusals throw.
 */
export async function ssoAccountCreateBefore(
  account: NewAccountData,
  ctx: SsoHookContext | null | undefined,
  deps: SsoResolutionDeps = defaultSsoResolutionDeps
): Promise<undefined> {
  const found = providerFor(ctx);
  if (!found) return undefined;
  const { provider } = found;
  const state = ssoRequestStore.getStore();
  const newUser = state?.newUser ?? null;
  const userId = typeof account.userId === 'string' ? account.userId : null;

  const discard = async () => {
    if (newUser && userId) await deps.discardNewUser(userId, newUser.passwordMarker).catch(() => undefined);
  };

  if (!provider) {
    await discard();
    return refuse(deps, null, ctx, SSO_ERROR_CODES.PROVIDER_NOT_FOUND, { userId: newUser ? null : userId });
  }
  const email = newUser?.email ?? canonicalizeEmail((await (userId ? deps.store.getUserById(userId) : null))?.email);
  if (!email || !emailInProviderDomains(email, provider)) {
    await discard();
    return refuse(deps, provider, ctx, SSO_ERROR_CODES.EMAIL_DOMAIN_MISMATCH, { email });
  }
  try {
    await checkOidcIdToken(deps, provider, ctx, account.idToken, email);
  } catch (error) {
    await discard();
    throw error;
  }

  if (!newUser) return undefined;

  // Brand-new user: the engine's sign-up path — a pending sign-up and the onboarding wizard.
  const accountId = typeof account.accountId === 'string' ? account.accountId : null;
  await discard();
  if (!accountId) return refuse(deps, provider, ctx, AUTH_ERROR_CODES.PROFILE_INCOMPLETE, { email, eventType: 'sign_up' });
  const pending = await deps.store.createPendingSignup(
    provider.identityKind,
    accountId,
    email,
    { access_token: null, refresh_token: null, expires_at: null, providerAccountId: accountId },
    { email, name: newUser.name, email_verified: true, sso_provider: provider.slug }
  );
  setOauthRedirectOverride(`/signup/oauth?token=${encodeURIComponent(pending.id)}`);
  await deps.recordEvent({
    event_type: 'sign_up',
    outcome: 'success',
    provider: provider.identityKind,
    user_label: email,
    ...clientDetails(ctx),
    detail: { protocol: provider.protocol, pending_signup: true },
  });
  // Stop core: the wizard creates the account. The handler retargets the redirect.
  throw new APIError('FOUND', { code: 'sso-signup-pending', message: 'sso-signup-pending' });
}

/** A session row as `session.create.before` receives it. */
type NewSessionData = Record<string, unknown> & { userId?: string };

/**
 * `databaseHooks.session.create.before`: an SSO sign-in is about to get a session.
 *
 * Runs the full engine for the `sso:<slug>` identity — a known identity signs in (refusing a
 * disabled, unverified or suspended account); an existing account with no binding yet is
 * auto-linked (the `external_auth_providers` row is written) — and records the outcome.
 *
 * @param session The session core is about to create.
 * @param ctx The endpoint context.
 * @param deps Injectable dependencies.
 * @returns undefined (admit) — refusals throw.
 */
export async function ssoSessionCreateBefore(
  session: NewSessionData,
  ctx: SsoHookContext | null | undefined,
  deps: SsoResolutionDeps = defaultSsoResolutionDeps
): Promise<undefined> {
  const found = providerFor(ctx);
  if (!found) return undefined;
  const { id, provider } = found;
  const userId = typeof session.userId === 'string' ? session.userId : null;
  if (!provider || !userId) return refuse(deps, provider, ctx, SSO_ERROR_CODES.PROVIDER_NOT_FOUND, { userId });

  const user = await deps.store.getUserById(userId);
  const email = canonicalizeEmail(user?.email);
  const accountId = await deps.accountIdFor(userId, id);
  if (!accountId) return refuse(deps, provider, ctx, AUTH_ERROR_CODES.PROFILE_INCOMPLETE, { userId, email });

  // The session core is creating is for `userId`; an apiome binding of this identity to anyone
  // else must refuse, never sign the other user in (the engine would adopt the bound user).
  const bound = await deps.store.getIdentity(provider.identityKind, accountId);
  if (bound.found && bound.userId && bound.userId !== userId) {
    return refuse(deps, provider, ctx, AUTH_ERROR_CODES.IDENTITY_LINKED_ELSEWHERE, { userId, email });
  }

  // The email was proven at account creation (domain + OIDC id token, or the SAML domain), so the
  // engine is told it is verified; the engine still refuses disabled / unverified / suspended users.
  const payload = {
    user: { email, name: user?.name ?? null },
    account: { provider: provider.identityKind, providerAccountId: accountId, email_verified: true },
    profile: { email, email_verified: true, sub: accountId },
  };
  let result: OAuthSignInResult;
  try {
    result = await resolveOAuthSignIn(provider.identityKind, payload, null, deps.store);
  } catch (error) {
    console.error('[ssoResolution] engine failed:', error instanceof Error ? error.name : 'unknown');
    result = false;
  }
  if (result !== true) {
    if (typeof result === 'string' && !result.startsWith('/login?error=')) {
      setOauthRedirectOverride(result);
      throw new APIError('FOUND', { code: 'sso-redirect', message: 'sso-redirect' });
    }
    const code = typeof result === 'string'
      ? (new URLSearchParams(result.split('?')[1] ?? '').get('error') as AuthErrorCode | null) ?? AUTH_ERROR_CODES.SIGN_IN_FAILED
      : AUTH_ERROR_CODES.SIGN_IN_FAILED;
    return refuse(deps, provider, ctx, code, { userId, email });
  }
  await deps.recordEvent({
    event_type: 'sign_in',
    outcome: 'success',
    provider: provider.identityKind,
    user_id: userId,
    user_label: email,
    ...clientDetails(ctx),
    detail: { protocol: provider.protocol },
  });
  return undefined;
}

/* ── Plugin-native failures ────────────────────────────────────────────────────────────────── */

/**
 * Map a failure the SSO plugin redirected with (`?error=<plugin code>`) to a stable `sso-*` code.
 *
 * @param pluginError The plugin's `error` query value.
 * @param description The plugin's `error_description`, when present.
 * @param protocol The provider's protocol, when known.
 * @returns The stable code.
 */
export function mapPluginError(
  pluginError: string,
  description: string | null,
  protocol: 'oidc' | 'saml' | null
): AuthErrorCode | SsoErrorCode {
  const error = pluginError.toLowerCase();
  const detail = (description ?? '').toLowerCase();
  if (error === 'replay_detected') return SSO_ERROR_CODES.ASSERTION_REPLAYED;
  if (error === 'invalid_state' || error === 'state_mismatch') return SSO_ERROR_CODES.STATE_INVALID;
  if (error === 'discovery_failed') return SSO_ERROR_CODES.DISCOVERY_FAILED;
  if (error === 'account_not_linked' || error === 'account not linked') return SSO_ERROR_CODES.ACCOUNT_NOT_LINKED;
  if (error === 'signup_disabled' || error === 'signup disabled') return AUTH_ERROR_CODES.SIGNUP_DISABLED;
  if (error === 'invalid_provider' && detail.includes('provider not found')) return SSO_ERROR_CODES.PROVIDER_NOT_FOUND;
  if (detail.includes('binding') || detail.includes('artifact')) return SSO_ERROR_CODES.BINDING_UNSUPPORTED;
  if (protocol === 'oidc') return SSO_ERROR_CODES.TOKEN_INVALID;
  if (protocol === 'saml') return SSO_ERROR_CODES.ASSERTION_INVALID;
  return AUTH_ERROR_CODES.SIGN_IN_FAILED;
}

/** The subset of an `after` hook context this handler reads. */
export interface SsoAfterContext extends SsoHookContext {
  context: {
    returned?: unknown;
    responseHeaders?: Headers;
  };
}

/**
 * `hooks.after` handler for SSO callbacks: turn a plugin-native failure into a stable `sso-*`
 * code on `/login` and record it. A no-op for non-SSO requests, for successes, and when one of the
 * database hooks above already decided the outcome (its override wins).
 *
 * @param rawCtx The Better Auth middleware context.
 * @param deps Injectable dependencies.
 * @param overrideAlreadySet Whether a hook already published the outcome (injectable for tests).
 */
export async function ssoCallbackAfterHandler(
  rawCtx: unknown,
  deps: SsoResolutionDeps = defaultSsoResolutionDeps,
  overrideAlreadySet: () => boolean = () => getOauthRedirectOverride() !== null
): Promise<void> {
  const ctx = rawCtx as SsoAfterContext;
  const found = providerFor(ctx);
  if (!found || overrideAlreadySet()) return;
  const returned = ctx.context?.returned as { headers?: Headers } | undefined;
  const location = returned?.headers?.get?.('location') ?? ctx.context?.responseHeaders?.get('location') ?? null;
  if (!location || !location.includes('error=')) return;
  let params: URLSearchParams;
  try {
    params = new URL(location, 'http://localhost').searchParams;
  } catch {
    return;
  }
  const pluginError = params.get('error');
  if (!pluginError) return;
  const code = mapPluginError(pluginError, params.get('error_description'), found.provider?.protocol ?? null);
  setOauthRedirectOverride(loginErrorRedirect(code as AuthErrorCode));
  await deps.recordEvent({
    event_type: 'sign_in',
    outcome: 'failure',
    provider: found.provider?.identityKind ?? `sso:${found.id.slice(SSO_PLUGIN_PROVIDER_PREFIX.length)}`.slice(0, 32),
    error_code: code,
    ...clientDetails(ctx),
    detail: { protocol: found.provider?.protocol ?? null, plugin_error: pluginError.slice(0, 64) },
  });
}

/**
 * `hooks.before` handler for the SAML ACS: refuse an HTTP-Artifact response (`SAMLart`) up front
 * with `sso-binding-unsupported` rather than letting it fail as a generic invalid response.
 *
 * @param rawCtx The Better Auth middleware context.
 * @param deps Injectable dependencies.
 */
export async function ssoArtifactBeforeHandler(
  rawCtx: unknown,
  deps: SsoResolutionDeps = defaultSsoResolutionDeps
): Promise<void> {
  const ctx = rawCtx as SsoHookContext & {
    body?: Record<string, unknown>;
    query?: Record<string, unknown>;
    redirect?: (url: string) => unknown;
  };
  const found = providerFor(ctx);
  if (!found) return;
  if (ctx.body?.SAMLart === undefined && ctx.query?.SAMLart === undefined) return;
  try {
    await refuse(deps, found.provider, ctx, SSO_ERROR_CODES.BINDING_UNSUPPORTED);
  } catch (error) {
    // A before hook answers with its own response: send the browser to the login page with the
    // code (refuse() has recorded the failure and published the same path as the override).
    if (ctx.redirect) throw ctx.redirect(loginErrorRedirect(SSO_ERROR_CODES.BINDING_UNSUPPORTED as unknown as AuthErrorCode));
    throw error;
  }
}
