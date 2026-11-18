/**
 * DB-over-env merge resolver for sign-in provider config (OLO-8.5, #4971).
 *
 * The whole auth stack reads provider config through `readEnvString(env, key)` with an injectable
 * `env` that has always defaulted to `process.env` (`provider-registry.ts`, OLO-2.3). This module
 * produces the merged `env` to inject instead: an **env-shaped overlay** where, for each provider
 * key (`GITHUB_ID`, `GITHUB_SECRET`, `GITLAB_CLIENT_ID`, `AZURE_AD_*`, provider base-URL/authority
 * extras), the value is the **DB value when set, else `process.env[key]`**. Feeding this to
 * `isProviderEnabled` / `enabledProviders` / the NextAuth provider factories makes DB config take
 * effect with `.env` as the fallback — with zero churn to those consumers (they still just read a
 * `readEnvString` env). OLO-8.6 will resolve this per request so a DB change lands without redeploy.
 *
 * Where the DB values come from: this is a **login-time** path (building providers before anyone is
 * authenticated), so there is no user or admin session to authorize a call. The decrypted config is
 * therefore read from apiome-rest's service-token-gated resolved endpoint (OLO-8.4/8.5,
 * `GET /v1/internal/auth-providers/resolved`) — the one place the KEK lives and decryption happens.
 * A short in-process TTL cache keeps this off the per-login hot path.
 *
 * Degrade-to-env, never break sign-in (OLO-8.6): if the token is unset, the endpoint is unreachable,
 * or it errors, the resolver returns the base env unchanged — login keeps working on `.env` config.
 * {@link resolveProviderEnvWithSource} additionally reports *which* of those happened, so boot-time
 * validation can tell "env is the whole truth" from "the DB source degraded" (OLO-8.8).
 *
 * Server-only: reads `INTERNAL_SERVICE_TOKEN` (a server secret) and calls apiome-rest. Import from
 * server code only (the NextAuth route / server components), never from a client component.
 */
import { REST_API_BASE_URL } from '../rest-auth';

/** An env-shaped map, matching the `readEnvString` seam's parameter type. */
export type EnvMap = Record<string, string | undefined>;

/**
 * Where the provider config in a resolved overlay actually came from (OLO-8.8, #4974).
 *
 * Boot-time validation needs this distinction, not just the merged env: whether a partially
 * configured provider is *really* an operator error depends on whether the DB source was consulted
 * successfully. See {@link resolveProviderEnvWithSource} and `provider-registry.validateProviderEnv`.
 *
 *   - `env-only`: `INTERNAL_SERVICE_TOKEN` is unset, so the DB source is deliberately switched off.
 *     Env is the whole truth and any gap in it is a real misconfiguration.
 *   - `db`: the resolved endpoint answered and its values are overlaid on env. What the merged env
 *     says is what login will see.
 *   - `unavailable`: the DB source *is* configured but could not be read (unreachable, non-200,
 *     malformed body). The overlay degraded to env, so the merged env may be missing values that
 *     are in fact stored in the database — it is not evidence of misconfiguration.
 */
export type ProviderConfigSource = 'env-only' | 'db' | 'unavailable';

/** A merged provider env together with the {@link ProviderConfigSource} it was built from. */
export interface ResolvedProviderEnv {
  /** The merged env-shaped overlay: DB value where set, else the base env value. */
  env: EnvMap;
  /** Where the config came from — see {@link ProviderConfigSource}. */
  source: ProviderConfigSource;
}

/** One provider's resolved DB config, as returned by the REST resolved endpoint. */
interface ResolvedProviderConfig {
  /** Explicit enable toggle; `null` ⇒ env-derived enablement. `false` ⇒ operator pinned it off. */
  enabled: boolean | null;
  /** OAuth client id, or `null`/blank to fall back to env. */
  client_id: string | null;
  /** Decrypted OAuth client secret, or `null`/blank to fall back to env. */
  client_secret: string | null;
  /** Non-secret provider extras, keyed by env var name (e.g. `GITLAB_BASE_URL`). */
  config: Record<string, unknown>;
}

/** Shape of the resolved endpoint payload: stored providers only, keyed by id. */
interface ResolvedProviderConfigResponse {
  providers: Record<string, ResolvedProviderConfig>;
}

/**
 * Env var names for each provider's client id / secret. The `config` extras are already env-var-keyed
 * in the DB (e.g. `{ "GITLAB_BASE_URL": "…" }`), so they are overlaid by their own key and need no
 * mapping here. Adding a provider means one entry here (mirroring `PROVIDER_REGISTRY`).
 */
export const PROVIDER_CRED_ENV_KEYS: Record<
  string,
  { clientId: string; clientSecret: string }
> = {
  github: { clientId: 'GITHUB_ID', clientSecret: 'GITHUB_SECRET' },
  gitlab: { clientId: 'GITLAB_CLIENT_ID', clientSecret: 'GITLAB_CLIENT_SECRET' },
  azure: { clientId: 'AZURE_AD_CLIENT_ID', clientSecret: 'AZURE_AD_CLIENT_SECRET' },
  // Google became a live provider after OLO-8.5 (OLO-9.2, #4985) and is in the store vocabulary
  // (V198) + the server registry, so its DB-configured credentials must overlay env like the others.
  google: { clientId: 'GOOGLE_CLIENT_ID', clientSecret: 'GOOGLE_CLIENT_SECRET' },
  // Okta (OLO-9.3, #4986): issuer lives in config JSONB and overlays via the extras loop below;
  // credentials still need an explicit mapping so DB-over-env enablement works.
  okta: { clientId: 'OKTA_CLIENT_ID', clientSecret: 'OKTA_CLIENT_SECRET' },
  // Cognito / aws (OLO-9.4, #4987): same issuer-in-config pattern as Okta.
  aws: { clientId: 'COGNITO_CLIENT_ID', clientSecret: 'COGNITO_CLIENT_SECRET' },
  // Keycloak (OLO-9.5, #4988): realm issuer lives in config JSONB; credentials overlay env.
  keycloak: { clientId: 'KEYCLOAK_CLIENT_ID', clientSecret: 'KEYCLOAK_CLIENT_SECRET' },
  // Generic OIDC (OLO-9.6, #4989): issuer (+ optional display name / scopes) in config JSONB.
  oidc: { clientId: 'OIDC_CLIENT_ID', clientSecret: 'OIDC_CLIENT_SECRET' },
  // Auth0 (OLO-9.7, #4990): tenant issuer lives in config JSONB; credentials overlay env.
  auth0: { clientId: 'AUTH0_CLIENT_ID', clientSecret: 'AUTH0_CLIENT_SECRET' },
  // LINE (OLO-9.41, #5054): credentials-only; no issuer extra.
  line: { clientId: 'LINE_CLIENT_ID', clientSecret: 'LINE_CLIENT_SECRET' },
  // VK ID (OLO-9.42, #5055): credentials-only; no issuer extra.
  vk: { clientId: 'VK_CLIENT_ID', clientSecret: 'VK_CLIENT_SECRET' },
  // WeChat Open Platform (OLO-9.43, #5056): credentials-only; no issuer extra.
  wechat: { clientId: 'WECHAT_CLIENT_ID', clientSecret: 'WECHAT_CLIENT_SECRET' },
  // Atlassian (OLO-9.8, #4991): credentials-only; fixed endpoints, no issuer extra.
  atlassian: { clientId: 'ATLASSIAN_CLIENT_ID', clientSecret: 'ATLASSIAN_CLIENT_SECRET' },
  // Bitbucket (OLO-9.9, #4992): credentials-only; fixed endpoints, no issuer extra.
  bitbucket: { clientId: 'BITBUCKET_CLIENT_ID', clientSecret: 'BITBUCKET_CLIENT_SECRET' },
  // Slack (OLO-9.17, #5030): credentials-only; fixed OIDC discovery document, no issuer extra.
  slack: { clientId: 'SLACK_CLIENT_ID', clientSecret: 'SLACK_CLIENT_SECRET' },
  // LinkedIn (OLO-9.18, #5031): credentials-only; fixed OIDC discovery document, no issuer extra.
  linkedin: { clientId: 'LINKEDIN_CLIENT_ID', clientSecret: 'LINKEDIN_CLIENT_SECRET' },
  // Discord (OLO-9.19, #5032): credentials-only; fixed endpoints, no issuer extra.
  discord: { clientId: 'DISCORD_CLIENT_ID', clientSecret: 'DISCORD_CLIENT_SECRET' },
  // Salesforce (OLO-9.20, #5033): the optional issuer (My Domain / sandbox) lives in config
  // JSONB and overlays via the extras loop below; credentials overlay env.
  salesforce: { clientId: 'SALESFORCE_CLIENT_ID', clientSecret: 'SALESFORCE_CLIENT_SECRET' },
  // Notion (OLO-9.21, #5034): credentials-only; fixed endpoints, no issuer extra.
  notion: { clientId: 'NOTION_CLIENT_ID', clientSecret: 'NOTION_CLIENT_SECRET' },
  // Figma (OLO-9.22, #5035): credentials-only; fixed endpoints, no issuer extra.
  figma: { clientId: 'FIGMA_CLIENT_ID', clientSecret: 'FIGMA_CLIENT_SECRET' },
  // Linear (OLO-9.23, #5036): credentials-only; fixed endpoints, no issuer extra.
  linear: { clientId: 'LINEAR_CLIENT_ID', clientSecret: 'LINEAR_CLIENT_SECRET' },
  // Dropbox (OLO-9.24, #5037): credentials-only; fixed endpoints, no issuer extra.
  dropbox: { clientId: 'DROPBOX_CLIENT_ID', clientSecret: 'DROPBOX_CLIENT_SECRET' },
  // Zoom (OLO-9.25, #5038): credentials-only; fixed endpoints, no issuer extra.
  zoom: { clientId: 'ZOOM_CLIENT_ID', clientSecret: 'ZOOM_CLIENT_SECRET' },
  // Hugging Face (OLO-9.26, #5039): credentials-only; fixed OIDC discovery document, no issuer extra.
  huggingface: {
    clientId: 'HUGGINGFACE_CLIENT_ID',
    clientSecret: 'HUGGINGFACE_CLIENT_SECRET',
  },
  // Vercel (OLO-9.27, #5040): credentials-only; fixed endpoints, no issuer extra.
  vercel: { clientId: 'VERCEL_CLIENT_ID', clientSecret: 'VERCEL_CLIENT_SECRET' },
  // Railway (OLO-9.28, #5041): credentials-only; fixed endpoints, no issuer extra.
  railway: { clientId: 'RAILWAY_CLIENT_ID', clientSecret: 'RAILWAY_CLIENT_SECRET' },
  // HubSpot (OLO-9.29, #5042): credentials-only; fixed endpoints, no issuer extra.
  hubspot: { clientId: 'HUBSPOT_CLIENT_ID', clientSecret: 'HUBSPOT_CLIENT_SECRET' },
  // Apple (OLO-9.30, #5043): the sealed secret is the .p8 private key; the Team ID and Key ID are
  // config extras that overlay via the extras loop below.
  apple: { clientId: 'APPLE_CLIENT_ID', clientSecret: 'APPLE_PRIVATE_KEY' },
  // Facebook (OLO-9.31, #5044): credentials-only; fixed endpoints, no issuer extra.
  facebook: { clientId: 'FACEBOOK_CLIENT_ID', clientSecret: 'FACEBOOK_CLIENT_SECRET' },
  // X / Twitter (OLO-9.32, #5045): credentials-only; fixed endpoints, no issuer extra.
  twitter: { clientId: 'TWITTER_CLIENT_ID', clientSecret: 'TWITTER_CLIENT_SECRET' },
  // Reddit (OLO-9.33, #5046): credentials-only; fixed endpoints, no issuer extra.
  reddit: { clientId: 'REDDIT_CLIENT_ID', clientSecret: 'REDDIT_CLIENT_SECRET' },
  // Spotify (OLO-9.34, #5047): credentials-only; fixed endpoints, no issuer extra.
  spotify: { clientId: 'SPOTIFY_CLIENT_ID', clientSecret: 'SPOTIFY_CLIENT_SECRET' },
  // Twitch (OLO-9.35, #5048): credentials-only; fixed OIDC discovery document, no issuer extra.
  twitch: { clientId: 'TWITCH_CLIENT_ID', clientSecret: 'TWITCH_CLIENT_SECRET' },
  // TikTok (OLO-9.36, #5049): credentials-only; the client ID is TikTok's "client key", fixed
  // endpoints, no issuer extra.
  tiktok: { clientId: 'TIKTOK_CLIENT_KEY', clientSecret: 'TIKTOK_CLIENT_SECRET' },
  // Roblox (OLO-9.37, #5050): credentials-only; fixed OIDC discovery document, no issuer extra.
  roblox: { clientId: 'ROBLOX_CLIENT_ID', clientSecret: 'ROBLOX_CLIENT_SECRET' },
  // Kick (OLO-9.38, #5051): credentials-only; fixed OAuth 2.1 endpoints, no issuer extra.
  kick: { clientId: 'KICK_CLIENT_ID', clientSecret: 'KICK_CLIENT_SECRET' },
  // PayPal (OLO-9.45, #5058): the optional environment (live / sandbox) lives in config JSONB
  // and overlays via the extras loop below; credentials overlay env.
  paypal: { clientId: 'PAYPAL_CLIENT_ID', clientSecret: 'PAYPAL_CLIENT_SECRET' },
  // Polar (OLO-9.46, #5059): credentials-only; fixed OAuth 2.0 / OIDC endpoints, no issuer extra.
  polar: { clientId: 'POLAR_CLIENT_ID', clientSecret: 'POLAR_CLIENT_SECRET' },
  // Patreon (OLO-9.47, #5060): credentials-only; fixed OAuth 2.0 endpoints, no issuer extra.
  patreon: { clientId: 'PATREON_CLIENT_ID', clientSecret: 'PATREON_CLIENT_SECRET' },
  // Gumroad (OLO-9.48, #5061): credentials-only; fixed OAuth 2.0 endpoints, no issuer extra.
  gumroad: { clientId: 'GUMROAD_CLIENT_ID', clientSecret: 'GUMROAD_CLIENT_SECRET' },
};

/** Default TTL (ms) for the in-process cache; bounded so a DB change lands within ~a cache window. */
const DEFAULT_CACHE_TTL_MS = 30_000;
/** Hard bounds on the configurable TTL so it can be neither zero (no cache) nor unboundedly stale. */
const MIN_CACHE_TTL_MS = 5_000;
const MAX_CACHE_TTL_MS = 60_000;
/** How long a *failed* fetch is cached, so an outage doesn't hammer REST but recovers quickly. */
const FAILURE_CACHE_TTL_MS = 5_000;
/** Bound on the resolved-endpoint call so a hung REST never stalls a login (degrades to env). */
const FETCH_TIMEOUT_MS = 2_000;

/**
 * Resolve the cache TTL from `AUTH_PROVIDER_CONFIG_CACHE_TTL_MS`, clamped to [MIN, MAX].
 *
 * @param env Environment to read (injectable for tests).
 * @returns The TTL in milliseconds.
 */
function cacheTtlMs(env: EnvMap): number {
  const raw = env.AUTH_PROVIDER_CONFIG_CACHE_TTL_MS;
  const parsed = raw ? Number(raw) : NaN;
  if (!Number.isFinite(parsed)) return DEFAULT_CACHE_TTL_MS;
  return Math.min(MAX_CACHE_TTL_MS, Math.max(MIN_CACHE_TTL_MS, Math.trunc(parsed)));
}

/** Outcome of one resolved-endpoint read: the payload (when any) plus where it left us. */
interface FetchOutcome {
  /** The parsed payload, or `null` when there is no DB overlay to apply. */
  value: ResolvedProviderConfigResponse | null;
  /** Why `value` is what it is — see {@link ProviderConfigSource}. */
  source: ProviderConfigSource;
}

interface CacheEntry {
  /** The resolved payload, or `null` when the last fetch failed / was skipped. */
  value: ResolvedProviderConfigResponse | null;
  /** The source that produced `value`, cached with it so callers see a consistent pair. */
  source: ProviderConfigSource;
  /** Epoch ms after which this entry is stale. */
  expiresAt: number;
}

/** Module-level in-process cache (per server instance). Reset via {@link invalidateProviderConfigCache}. */
let cache: CacheEntry | null = null;

/**
 * Clear the in-process resolved-config cache.
 *
 * The invalidation hook the issue calls for: an OLO-8.4 write in the *same* process can call this so
 * the next resolve re-fetches immediately instead of serving up to one TTL of staleness. (Admin
 * writes land in apiome-rest, a different process, so cross-process freshness still relies on the
 * bounded TTL — accepted by the issue.) Also used by tests to isolate cases.
 */
export function invalidateProviderConfigCache(): void {
  cache = null;
  missingTokenNoticeLogged = false;
}

/**
 * Whether the "no service token" notice has already been emitted in this process.
 *
 * Running without the token is a legitimate configuration (providers come from env alone), so it is
 * not a warning on every login — but it is also the state in which admin-screen provider config
 * silently has no effect, which is indistinguishable from a bug unless something says so once.
 */
let missingTokenNoticeLogged = false;

/**
 * Whether a candidate override value is present (a non-blank string). Blank ⇒ treated as absent so
 * the env value is kept — "blank DB field ⇒ fallback, not disabled" (issue AC).
 *
 * @param value The candidate value.
 * @returns True when `value` is a string with non-whitespace content.
 */
function isPresent(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Fetch the resolved provider config from apiome-rest.
 *
 * Never throws. When the service token is unset the read path is off (`env-only`); when the endpoint
 * is unreachable, times out, responds non-200, or returns a body of the wrong shape, the payload is
 * `null` and the source is `unavailable` — the caller degrades to env either way, but only the first
 * case is evidence that env is the whole truth (OLO-8.8). Never logs the response body (it carries
 * decrypted secrets).
 *
 * @param env Environment to read the service token from (injectable for tests).
 * @returns The parsed payload and the {@link ProviderConfigSource} that produced it.
 */
async function fetchResolvedProviderConfig(env: EnvMap): Promise<FetchOutcome> {
  const token = env.INTERNAL_SERVICE_TOKEN?.trim();
  if (!token) {
    // No token ⇒ the resolved read path is disabled; run on env alone. Not an error — but say so
    // once per process, because otherwise the *only* observable difference between "configured
    // from env on purpose" and "the deploy dropped the token" is that admin-screen provider
    // config quietly does nothing. Once, not per login: this is a startup-shaped fact.
    if (!missingTokenNoticeLogged) {
      missingTokenNoticeLogged = true;
      console.warn(
        '[provider-config-resolver] INTERNAL_SERVICE_TOKEN is not set; sign-in providers are ' +
          'configured from env only, and admin-screen provider config will have no effect'
      );
    }
    return { value: null, source: 'env-only' };
  }

  // Prefer the runtime REST_API_BASE_URL: Next inlines NEXT_PUBLIC_* into the server bundle at build
  // time, so an image built without it carries the localhost default no matter what the container's
  // environment says — and inside a container localhost is the container itself.
  const runtimeBaseUrl = env.REST_API_BASE_URL?.trim().replace(/\/+$/, '');
  const resolvedUrl = `${runtimeBaseUrl || REST_API_BASE_URL}/internal/auth-providers/resolved`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(resolvedUrl, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Service-Token': token,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      // 5xx/4xx (e.g. 503 when REST has no token) ⇒ degrade to env silently. No secret in the body.
      console.warn(
        `[provider-config-resolver] resolved endpoint returned ${response.status}; using env config`
      );
      return { value: null, source: 'unavailable' };
    }
    const data = (await response.json()) as ResolvedProviderConfigResponse;
    if (!data || typeof data !== 'object' || typeof data.providers !== 'object') {
      // A 200 with the wrong shape is as unusable as an outage — and just as much a reason not to
      // treat env as authoritative. Shape only, never the body (it carries decrypted secrets).
      console.warn(
        '[provider-config-resolver] resolved endpoint returned an unexpected payload shape; ' +
          'using env config'
      );
      return { value: null, source: 'unavailable' };
    }
    return { value: data, source: 'db' };
  } catch (error) {
    // Network error / timeout / abort. Degrade to env; message only, never the (secret-bearing) body.
    // Name the URL and the underlying cause (ECONNREFUSED, ENOTFOUND, …): fetch's bare `TypeError`
    // does not say which address was unreachable, and that address is what is misconfigured.
    // Neither carries a secret — the token travels in a header.
    const cause = error instanceof Error ? (error.cause as { code?: unknown } | undefined) : undefined;
    const code = typeof cause?.code === 'string' ? `: ${cause.code}` : '';
    console.warn(
      `[provider-config-resolver] resolved endpoint fetch to ${resolvedUrl} failed (${
        error instanceof Error ? error.name : 'unknown'
      }${code}); using env config`
    );
    return { value: null, source: 'unavailable' };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Get the resolved config through the TTL cache, fetching on miss/expiry.
 *
 * @param env Environment (for the token and TTL).
 * @param now Current epoch ms (injectable for tests).
 * @returns The cached-or-fresh payload with its {@link ProviderConfigSource}.
 */
async function getResolvedProviderConfig(env: EnvMap, now: number): Promise<FetchOutcome> {
  if (cache && cache.expiresAt > now) {
    return { value: cache.value, source: cache.source };
  }
  const outcome = await fetchResolvedProviderConfig(env);
  // Successful fetches are cached for the full TTL; anything else for a short window so an outage
  // neither hammers REST nor lingers once it recovers.
  const ttl = outcome.source === 'db' ? cacheTtlMs(env) : FAILURE_CACHE_TTL_MS;
  cache = { value: outcome.value, source: outcome.source, expiresAt: now + ttl };
  return outcome;
}

/**
 * Overlay the resolved DB config onto a base env, returning the merged env-shaped map.
 *
 * For each stored provider: its client id/secret override the corresponding env keys when present;
 * its `config` extras override their (env-var-named) keys when present; a blank DB value is treated
 * as absent (env kept). A provider explicitly pinned **off** (`enabled === false`) has its cred keys
 * removed from the overlay so `isProviderEnabled` computes `false` even if env still sets them.
 *
 * @param baseEnv The base environment (typically `process.env`).
 * @param resolved The resolved DB payload, or `null` to return `baseEnv` unchanged.
 * @returns A new merged env map; `baseEnv` is never mutated.
 */
export function applyResolvedOverlay(
  baseEnv: EnvMap,
  resolved: ResolvedProviderConfigResponse | null
): EnvMap {
  const overlay: EnvMap = { ...baseEnv };
  if (!resolved) return overlay;

  for (const [providerId, cfg] of Object.entries(resolved.providers)) {
    if (!cfg) continue;
    const keys = PROVIDER_CRED_ENV_KEYS[providerId];

    // Explicit off: strip creds so the provider is disabled regardless of env (V196 `enabled=false`).
    if (cfg.enabled === false && keys) {
      delete overlay[keys.clientId];
      delete overlay[keys.clientSecret];
      continue;
    }

    if (keys) {
      if (isPresent(cfg.client_id)) overlay[keys.clientId] = cfg.client_id;
      if (isPresent(cfg.client_secret)) overlay[keys.clientSecret] = cfg.client_secret;
    }

    // Provider extras are already env-var-keyed; overlay each present value.
    for (const [key, value] of Object.entries(cfg.config ?? {})) {
      if (isPresent(value)) overlay[key] = value;
    }
  }

  return overlay;
}

/**
 * Resolve the merged provider env *and* report where its config came from (OLO-8.8).
 *
 * Same merge as {@link resolveProviderEnv}, but the caller also learns whether the DB source was
 * consulted successfully. Boot-time validation needs that: with `unavailable`, a provider that looks
 * partially configured in the merged env may simply be one whose stored config could not be read,
 * which is not grounds for refusing to start.
 *
 * @param baseEnv Base environment; defaults to `process.env`.
 * @param now Current epoch ms (injectable for tests; defaults to `Date.now()`).
 * @returns The merged overlay and its {@link ProviderConfigSource}. Never throws.
 */
export async function resolveProviderEnvWithSource(
  baseEnv: EnvMap = process.env,
  now: number = Date.now()
): Promise<ResolvedProviderEnv> {
  const { value, source } = await getResolvedProviderConfig(baseEnv, now);
  return { env: applyResolvedOverlay(baseEnv, value), source };
}

/**
 * Resolve the merged provider env: DB value where set, else `baseEnv`.
 *
 * This is the injectable `env` the rest of the auth stack should read through — pass its result to
 * `isProviderEnabled`, `enabledProviders`, and the NextAuth provider factories. Never throws:
 * on any failure to reach the DB config it returns `baseEnv` unchanged (degrade to env).
 *
 * @param baseEnv Base environment; defaults to `process.env`.
 * @param now Current epoch ms (injectable for tests; defaults to `Date.now()`).
 * @returns The merged env-shaped overlay.
 */
export async function resolveProviderEnv(
  baseEnv: EnvMap = process.env,
  now: number = Date.now()
): Promise<EnvMap> {
  return (await resolveProviderEnvWithSource(baseEnv, now)).env;
}
