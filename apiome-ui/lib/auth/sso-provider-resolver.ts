/**
 * The enterprise SSO providers sign-in can route to right now (EID-1.1, #5011).
 *
 * A workspace's own SAML 2.0 / OIDC identity provider is registered in apiome-rest (admin console →
 * `/v1/admin/sso/providers`, V312). At sign-in time this module reads the **routable** set — enabled
 * providers and their **verified** domains, secrets decrypted — from the service-token-gated
 * `GET /v1/internal/sso/providers/resolved`, and turns it into the `defaultSSO` entries Better
 * Auth's SSO plugin reads. That makes apiome's tables, not the plugin's own `ssoProvider` table, the
 * source of truth: the plugin's model points at an always-empty view (V312), so a disabled or
 * unverified provider cannot be reached by any route.
 *
 * Shape of the mapping:
 *
 * - **providerId** is `sso-<slug>` (the plugin's id, in every sign-in URL), so Better Auth's
 *   `account.providerId` can never collide with an OAuth provider id; the identity apiome records is
 *   `sso:<slug>` ({@link ResolvedSsoProvider.identityKind}).
 * - **One entry per verified domain**: the plugin matches a sign-in email against one `domain` per
 *   entry, and every entry of a provider carries the same `providerId` and config.
 * - **SAML email**: the plugin reads `mapping.email` and falls back to the NameID. For an IdP whose
 *   email *is* the NameID, `mapping.email` names an attribute no IdP sends, so the NameID is always
 *   used — never an `email` attribute the admin did not choose.
 *
 * Never throws and never logs a response body (it carries decrypted secrets): an unreachable REST
 * API, a missing token or a malformed payload all mean "no SSO providers", so password and OAuth
 * sign-in keep working.
 */

import { createHash } from 'node:crypto';
import { REST_API_BASE_URL } from '../rest-auth';

/** The plugin's id prefix: a provider `acme` is `sso-acme` in Better Auth. */
export const SSO_PLUGIN_PROVIDER_PREFIX = 'sso-';

/** The identity-kind prefix apiome records: `sso:acme`. */
export const SSO_IDENTITY_PREFIX = 'sso:';

/** The SSO plugin routes that complete a sign-in (OIDC callback, SAML ACS / callback). */
export const SSO_CALLBACK_PREFIXES = ['/sso/callback/', '/sso/saml2/sp/acs/', '/sso/saml2/callback/'] as const;

/**
 * An attribute name no IdP sends, so the plugin's `attr(mapping.email) || nameID` falls back to
 * the NameID when the provider's email source is the NameID.
 */
export const SAML_NAMEID_EMAIL_SENTINEL = '__apiome_email_from_nameid__';

/** How long a read is reused, and how long a failed read is (shorter, so recovery is quick). */
const CACHE_TTL_MS = 30_000;
const FAILURE_CACHE_TTL_MS = 5_000;
const FETCH_TIMEOUT_MS = 2_000;

/** One routable provider, as the internal endpoint returns it. Carries decrypted secrets. */
export interface ResolvedSsoProvider {
  id: string;
  slug: string;
  pluginProviderId: string;
  identityKind: string;
  protocol: 'oidc' | 'saml';
  displayName: string;
  issuer: string;
  tenantId: string | null;
  /** Verified domains only. */
  domains: string[];
  oidcConfig: Record<string, unknown> | null;
  samlConfig: Record<string, unknown> | null;
  clientSecret: string | null;
  spPrivateKey: string | null;
}

/** The routable set and a secret-free fingerprint that changes whenever it does. */
export interface ResolvedSsoProviders {
  providers: ResolvedSsoProvider[];
  fingerprint: string;
}

/** A `defaultSSO` entry as `@better-auth/sso` reads it. */
export interface DefaultSsoEntry {
  domain: string;
  providerId: string;
  oidcConfig?: Record<string, unknown>;
  samlConfig?: Record<string, unknown>;
}

type EnvMap = Record<string, string | undefined>;

/** The empty set: what sign-in uses whenever the routable set cannot be read. */
export const NO_SSO_PROVIDERS: ResolvedSsoProviders = Object.freeze({
  providers: [],
  fingerprint: 'none',
}) as ResolvedSsoProviders;

let cache: { at: number; ttl: number; value: ResolvedSsoProviders } | null = null;

/** Drop the cached read (tests; and the admin proxy after a write in this process). */
export function invalidateSsoProviderCache(): void {
  cache = null;
}

/**
 * Map one wire row (snake_case) onto {@link ResolvedSsoProvider}, or `null` when it is malformed.
 *
 * @param row One element of the endpoint's `providers` array.
 * @returns The provider, or null for a row missing an id, slug, protocol or domain.
 */
export function parseResolvedProvider(row: unknown): ResolvedSsoProvider | null {
  if (!row || typeof row !== 'object') return null;
  const r = row as Record<string, unknown>;
  const slug = typeof r.slug === 'string' ? r.slug : '';
  const protocol = r.protocol === 'oidc' || r.protocol === 'saml' ? r.protocol : null;
  const domains = Array.isArray(r.domains) ? r.domains.filter((d): d is string => typeof d === 'string') : [];
  if (!slug || !protocol || typeof r.id !== 'string' || domains.length === 0) return null;
  const record = (value: unknown) =>
    value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  const text = (value: unknown) => (typeof value === 'string' && value.length > 0 ? value : null);
  return {
    id: r.id,
    slug,
    pluginProviderId: text(r.plugin_provider_id) ?? `${SSO_PLUGIN_PROVIDER_PREFIX}${slug}`,
    identityKind: text(r.identity_kind) ?? `${SSO_IDENTITY_PREFIX}${slug}`,
    protocol,
    displayName: text(r.display_name) ?? slug,
    issuer: text(r.issuer) ?? '',
    tenantId: text(r.tenant_id),
    domains: domains.map((d) => d.toLowerCase()),
    oidcConfig: record(r.oidc_config),
    samlConfig: record(r.saml_config),
    clientSecret: text(r.client_secret),
    spPrivateKey: text(r.sp_private_key),
  };
}

/**
 * Read the routable providers (TTL-cached). Never throws.
 *
 * @param env Environment to read `INTERNAL_SERVICE_TOKEN` / `REST_API_BASE_URL` from.
 * @param now Current epoch ms (injectable for tests).
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The routable set, or {@link NO_SSO_PROVIDERS} when it cannot be read.
 */
export async function resolveSsoProviders(
  env: EnvMap = process.env,
  now: number = Date.now(),
  fetchImpl: typeof fetch = fetch
): Promise<ResolvedSsoProviders> {
  if (cache && now - cache.at < cache.ttl) return cache.value;

  const token = env.INTERNAL_SERVICE_TOKEN?.trim();
  if (!token) {
    cache = { at: now, ttl: CACHE_TTL_MS, value: NO_SSO_PROVIDERS };
    return NO_SSO_PROVIDERS;
  }

  const base = env.REST_API_BASE_URL?.trim().replace(/\/+$/, '') || REST_API_BASE_URL;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(`${base}/internal/sso/providers/resolved`, {
      method: 'GET',
      cache: 'no-store',
      headers: { 'X-Internal-Service-Token': token },
      signal: controller.signal,
    });
    if (!response.ok) {
      console.warn(`[sso-provider-resolver] resolved endpoint returned ${response.status}; no SSO providers`);
      cache = { at: now, ttl: FAILURE_CACHE_TTL_MS, value: NO_SSO_PROVIDERS };
      return NO_SSO_PROVIDERS;
    }
    const data = (await response.json()) as { providers?: unknown; fingerprint?: unknown };
    const providers = Array.isArray(data?.providers)
      ? data.providers.map(parseResolvedProvider).filter((p): p is ResolvedSsoProvider => p !== null)
      : [];
    const value: ResolvedSsoProviders = {
      providers,
      fingerprint:
        typeof data?.fingerprint === 'string' && data.fingerprint
          ? data.fingerprint
          : createHash('sha256').update(JSON.stringify(providers.map((p) => p.id))).digest('hex'),
    };
    cache = { at: now, ttl: CACHE_TTL_MS, value };
    return value;
  } catch (error) {
    console.warn(
      `[sso-provider-resolver] resolved endpoint unreachable (${error instanceof Error ? error.name : 'unknown'}); no SSO providers`
    );
    cache = { at: now, ttl: FAILURE_CACHE_TTL_MS, value: NO_SSO_PROVIDERS };
    return NO_SSO_PROVIDERS;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The SAML SP entity id apiome presents for a provider: its SP metadata URL, which is the value an
 * IdP admin pastes as "Audience" / "Entity ID".
 *
 * @param baseURL Better Auth's base URL (`…/api/auth`).
 * @param pluginProviderId `sso-<slug>`.
 * @returns The SP entity id.
 */
export function samlSpEntityId(baseURL: string, pluginProviderId: string): string {
  return `${baseURL.replace(/\/+$/, '')}/sso/saml2/sp/metadata?providerId=${encodeURIComponent(pluginProviderId)}`;
}

/**
 * The plugin config for one provider, shared by every domain entry.
 *
 * @param provider A routable provider.
 * @param baseURL Better Auth's base URL (`…/api/auth`), for the SAML ACS and SP entity id.
 * @returns `{ oidcConfig }` or `{ samlConfig }`, or null when the stored config is unusable.
 */
export function pluginConfigFor(
  provider: ResolvedSsoProvider,
  baseURL: string
): Pick<DefaultSsoEntry, 'oidcConfig' | 'samlConfig'> | null {
  const str = (v: unknown) => (typeof v === 'string' && v ? v : undefined);
  if (provider.protocol === 'oidc') {
    const c = provider.oidcConfig ?? {};
    const clientId = str(c.client_id);
    if (!clientId || !provider.clientSecret) return null;
    return {
      oidcConfig: {
        issuer: provider.issuer,
        pkce: c.pkce !== false,
        clientId,
        clientSecret: provider.clientSecret,
        discoveryEndpoint: str(c.discovery_endpoint) ?? `${provider.issuer.replace(/\/+$/, '')}/.well-known/openid-configuration`,
        authorizationEndpoint: str(c.authorization_endpoint),
        tokenEndpoint: str(c.token_endpoint),
        jwksEndpoint: str(c.jwks_uri),
        userInfoEndpoint: str(c.userinfo_endpoint),
        scopes: Array.isArray(c.scopes) ? c.scopes : ['openid', 'email', 'profile'],
        tokenEndpointAuthentication:
          c.token_endpoint_authentication === 'client_secret_post' ? 'client_secret_post' : 'client_secret_basic',
      },
    };
  }
  const c = provider.samlConfig ?? {};
  const entryPoint = str(c.sso_url);
  const certificates = Array.isArray(c.certificates) ? c.certificates.filter((x): x is string => typeof x === 'string') : [];
  const idpEntityId = str(c.idp_entity_id) ?? provider.issuer;
  if (!entryPoint || certificates.length === 0 || !idpEntityId) return null;
  const acs = `${baseURL.replace(/\/+$/, '')}/sso/saml2/sp/acs/${encodeURIComponent(provider.pluginProviderId)}`;
  const emailAttribute = c.email_source === 'attribute' ? str(c.email_attribute) : undefined;
  return {
    samlConfig: {
      issuer: idpEntityId,
      entryPoint,
      cert: certificates[0],
      callbackUrl: acs,
      wantAssertionsSigned: true,
      idpMetadata: {
        entityID: idpEntityId,
        cert: certificates[0],
        singleSignOnService: [{ Binding: str(c.sso_binding) ?? 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect', Location: entryPoint }],
      },
      spMetadata: {
        entityID: samlSpEntityId(baseURL, provider.pluginProviderId),
        ...(provider.spPrivateKey ? { privateKey: provider.spPrivateKey } : {}),
      },
      ...(provider.spPrivateKey ? { privateKey: provider.spPrivateKey, authnRequestsSigned: true } : {}),
      mapping: { email: emailAttribute ?? SAML_NAMEID_EMAIL_SENTINEL },
    },
  };
}

/**
 * Turn the routable set into Better Auth `defaultSSO` entries — one per verified domain.
 *
 * @param resolved The routable set.
 * @param baseURL Better Auth's base URL (`…/api/auth`).
 * @returns The entries; a provider whose stored config is unusable contributes none.
 */
export function buildDefaultSsoEntries(resolved: ResolvedSsoProviders, baseURL: string): DefaultSsoEntry[] {
  const entries: DefaultSsoEntry[] = [];
  for (const provider of resolved.providers) {
    const config = pluginConfigFor(provider, baseURL);
    if (!config) continue;
    for (const domain of provider.domains) {
      entries.push({ domain, providerId: provider.pluginProviderId, ...config });
    }
  }
  return entries;
}

/**
 * Find a routable provider by the plugin's id (`sso-<slug>`).
 *
 * @param resolved The routable set.
 * @param pluginProviderId The id from the sign-in URL.
 * @returns The provider, or null.
 */
export function findSsoProvider(resolved: ResolvedSsoProviders, pluginProviderId: string | null | undefined): ResolvedSsoProvider | null {
  if (!pluginProviderId) return null;
  return resolved.providers.find((p) => p.pluginProviderId === pluginProviderId) ?? null;
}
