/**
 * Support for the OLO-8.9 provider-config journey (#4975).
 *
 * Two jobs, both of which exist because the database config source is *optional* infrastructure:
 *
 *   1. {@link providerConfigSourceReady} — a precondition probe. The journey's Playwright config
 *      starts the mock provider and the UI dev server, but **not** REST; REST is whatever the
 *      operator already has running, and the three variables this story depends on
 *      (`INTERNAL_SERVICE_TOKEN`, `ADMIN_SESSION_SECRET`, `AUTH_CONFIG_ENC_KEY`) all default to
 *      empty in `docker-compose.yml`. Rather than fail as an opaque 403 or a login page that
 *      silently kept using `.env`, the spec asks first and skips with the reason.
 *   2. {@link captureAuthorizeClientId} — the assertion seam. The whole point of OLO-8 is *which*
 *      credentials a sign-in uses, and the only place that is observable from the browser is the
 *      OAuth authorization request the app makes after resolving its provider config.
 */
import type { Page } from '@playwright/test';
import { restApiBaseUrl } from './env';

/**
 * Resolver cache TTL the journey pins in `journeyServerEnv()` — the floor
 * `provider-config-resolver.ts` clamps to. Waits after a config change are derived from it.
 */
export const PROVIDER_CONFIG_CACHE_TTL_MS = 5_000;

/** Slack added to the TTL when waiting for an admin edit to reach the login path. */
const CACHE_SETTLE_SLACK_MS = 1_500;

/** How long {@link waitForResolvedConfig} keeps asking REST before giving up. */
const RESOLVED_POLL_TIMEOUT_MS = 10_000;
/** Gap between polls of the resolved endpoint. */
const RESOLVED_POLL_INTERVAL_MS = 250;

/** One provider's stored config as the service-token endpoint reports it. */
export interface ResolvedProviderConfig {
  /** Explicit enablement; `null` means enablement is derived from `.env`. */
  enabled: boolean | null;
  /** Stored client id, or `null` when the provider falls back to `.env`. */
  client_id: string | null;
  /** Decrypted client secret, or `null` when none is stored. */
  client_secret: string | null;
  /** Non-secret extras, keyed by env var name. */
  config: Record<string, unknown>;
}

/** Whether the database config source can be exercised, and why not when it cannot. */
export interface ProviderConfigReadiness {
  /** True when REST answers the resolved endpoint and the admin password is available. */
  ready: boolean;
  /** Operator-facing explanation naming the missing piece; empty when {@link ready}. */
  reason: string;
}

/** The service token shared by the app under test and REST; empty when the source is switched off. */
function serviceToken(): string {
  return process.env.INTERNAL_SERVICE_TOKEN ?? '';
}

/** REST's root URL (the resolved endpoint lives outside the `/v1` prefix helper's path). */
function restRoot(): string {
  return restApiBaseUrl().replace(/\/v1\/?$/, '');
}

/**
 * Ask REST for every stored provider configuration.
 *
 * @returns The `providers` map, keyed by provider slug. Providers with no stored row are absent,
 *   as is any provider whose secret could not be decrypted (REST omits those deliberately).
 * @throws Error when the endpoint is unreachable or refuses the token.
 */
export async function fetchResolvedProviders(): Promise<Record<string, ResolvedProviderConfig>> {
  const response = await fetch(`${restRoot()}/v1/internal/auth-providers/resolved`, {
    headers: { 'X-Internal-Service-Token': serviceToken() },
  });
  if (!response.ok) {
    throw new Error(
      `resolved provider config: HTTP ${response.status} from ${restRoot()} ` +
        '(INTERNAL_SERVICE_TOKEN must match apiome-rest byte for byte)'
    );
  }
  const body = (await response.json()) as { providers?: Record<string, ResolvedProviderConfig> };
  return body.providers ?? {};
}

/**
 * Decide whether the provider-config story can run against the stack that is actually up.
 *
 * Checks, in the order an operator would fix them: the service token is set here, REST accepts it
 * on the resolved endpoint, and an admin password exists for the `/admin` sign-in.
 *
 * The encryption key (`AUTH_CONFIG_ENC_KEY`) is deliberately **not** probed — nothing reads it
 * until a secret is written, and REST reports its absence precisely (`encryption_not_configured`)
 * at that point, which the spec surfaces in its failure message.
 *
 * @returns Readiness plus, when not ready, the variable to set and where.
 */
export async function providerConfigSourceReady(): Promise<ProviderConfigReadiness> {
  if (!serviceToken()) {
    return {
      ready: false,
      reason:
        'INTERNAL_SERVICE_TOKEN is not set, so the database config source is switched off ' +
        '(resolveProviderEnv stays on .env). Set it in apiome-ui/.env AND apiome-rest/.env, ' +
        'identically.',
    };
  }

  if (!process.env.ADMIN_PASSWORD) {
    return {
      ready: false,
      reason:
        'ADMIN_PASSWORD is not set, so the spec cannot sign in to the /admin portal. Set it in ' +
        'apiome-ui/.env (and mirror ADMIN_SESSION_SECRET into apiome-rest/.env so REST accepts ' +
        'the forwarded session).',
    };
  }

  try {
    await fetchResolvedProviders();
  } catch (error) {
    return { ready: false, reason: String(error) };
  }

  return { ready: true, reason: '' };
}

/**
 * Poll REST until a provider's stored config satisfies `predicate`.
 *
 * Used after an admin edit to prove the write reached the database *before* waiting on the app's
 * in-process cache — so a failure says which half is at fault instead of timing out in the browser.
 *
 * @param providerId Provider slug, e.g. `github`.
 * @param predicate Receives the stored config, or `null` when the provider has no row.
 * @throws Error when the predicate is still unsatisfied at the timeout.
 */
export async function waitForResolvedConfig(
  providerId: string,
  predicate: (config: ResolvedProviderConfig | null) => boolean
): Promise<void> {
  const deadline = Date.now() + RESOLVED_POLL_TIMEOUT_MS;
  let last: ResolvedProviderConfig | null = null;
  while (Date.now() < deadline) {
    last = (await fetchResolvedProviders())[providerId] ?? null;
    if (predicate(last)) return;
    await new Promise((done) => setTimeout(done, RESOLVED_POLL_INTERVAL_MS));
  }
  throw new Error(
    `REST still reports ${providerId} as ${JSON.stringify(last)} after ` +
      `${RESOLVED_POLL_TIMEOUT_MS}ms — the admin write did not reach the database.`
  );
}

/**
 * Wait out the app's provider-config cache so the next sign-in rebuilds from the current database
 * state.
 *
 * The resolver's cache is in-process in the Next.js server, so a test cannot invalidate it from
 * outside; the TTL is pinned to its 5s floor in `journeyServerEnv()` precisely so this wait stays
 * short and bounded. Call {@link waitForResolvedConfig} first — this only covers the UI's cache,
 * not the write.
 *
 * @param page Page whose context provides the clock.
 */
export async function waitOutProviderConfigCache(page: Page): Promise<void> {
  await page.waitForTimeout(PROVIDER_CONFIG_CACHE_TTL_MS + CACHE_SETTLE_SLACK_MS);
}

/**
 * Run `action` (a click that starts an OAuth sign-in) and report the `client_id` the app actually
 * sent to the provider.
 *
 * This is the DB-over-env proof. The client id is chosen server-side while Better Auth's provider
 * config is rebuilt from the merged env, so the outgoing authorization request is the first and
 * only place it becomes visible. Observing the *request* rather than the `sign-in/oauth2` response
 * body is deliberate: it is what the provider genuinely receives, and it cannot be lost to response
 * buffering when the page navigates away.
 *
 * The mock provider ignores `client_id` entirely, so the sign-in still completes whichever value
 * goes out — which is what lets the spec assert precedence without breaking the journey.
 *
 * @param page Page the sign-in runs in.
 * @param authorizePathFragment Path fragment identifying the provider's authorize endpoint, e.g.
 *   `/github/login/oauth/authorize`.
 * @param action Starts the sign-in — typically clicking the provider's login button.
 * @returns The `client_id` query parameter of the authorization request.
 * @throws Error when the authorization request carries no `client_id`.
 */
export async function captureAuthorizeClientId(
  page: Page,
  authorizePathFragment: string,
  action: () => Promise<void>
): Promise<string> {
  // Generous timeout: the click round-trips through `sign-in/oauth2`, which rebuilds the Better Auth
  // instance from the merged env (and may re-read REST) before it hands back a redirect URL.
  const authorizeRequest = page.waitForRequest(
    (request) => request.url().includes(authorizePathFragment),
    { timeout: 60_000 }
  );
  await action();
  const url = new URL((await authorizeRequest).url());
  const clientId = url.searchParams.get('client_id');
  if (!clientId) {
    throw new Error(`authorization request carried no client_id: ${url.toString()}`);
  }
  return clientId;
}
