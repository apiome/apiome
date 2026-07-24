/**
 * @jest-environment node
 *
 * Per-request Better Auth provider resolution tests (OLO-10.8, #5003).
 *
 * `resolveRequestAuthInstance` is the Better Auth counterpart of the NextAuth per-request rebuild
 * (OLO-8.6): it resolves the DB-over-env merged config (OLO-8.5) and, because Better Auth freezes the
 * `genericOAuth` config when the instance is constructed, builds (or reuses) a Better Auth instance
 * whose provider set reflects that config — so a DB toggle from the admin settings screen changes the
 * enabled provider set on the next sign-in with no redeploy. These tests pin the acceptance criteria
 * at the seam `betterAuthHandler` actually calls:
 *
 *   - a DB-enabled provider not present in env appears in the resolved provider set,
 *   - `enabled === false` in the DB pins an env-configured provider off,
 *   - the DB client id/secret override the env values,
 *   - google (added to the resolver's cred map in this ticket) is DB-overridable like the rest,
 *   - env-only providers still resolve and no DB read is attempted without a service token,
 *   - every DB failure mode (non-200, network error) degrades to the env provider set — never a
 *     login outage,
 *   - the instance is cached by its provider-config fingerprint: unchanged config reuses the
 *     instance, an admin edit rebuilds it.
 *
 * `better-auth` (and its plugins) ship ESM-only, which ts-jest's CommonJS transform cannot `require`,
 * so they — and the Postgres pool and the REST base URL — are mocked, exactly as `better-auth-core`
 * does. The `genericOAuth` mock preserves the `config` array it is handed so the tests can read the
 * resolved provider set out of it.
 */

const mockHandler = jest.fn();
const mockBetterAuth = jest.fn(() => ({ handler: mockHandler }));
const mockNextCookies = jest.fn(() => ({ id: 'next-cookies' }));
/** Preserve the config array so a test can read the resolved provider set the instance was built on. */
const mockGenericOAuth = jest.fn((opts: { config: unknown }) => ({
  id: 'generic-oauth',
  config: opts.config,
}));

jest.mock('better-auth', () => ({ betterAuth: mockBetterAuth }));
jest.mock('better-auth/next-js', () => ({ nextCookies: mockNextCookies }));
jest.mock('better-auth/plugins/generic-oauth', () => ({ genericOAuth: mockGenericOAuth }));
// The OLO-10.10 twoFactor plugin is registered on the instance auth.ts builds; stub it (better-auth
// is ESM-only) so the per-request rebuild loads under ts-jest.
jest.mock('better-auth/plugins/two-factor', () => ({ twoFactor: jest.fn(() => ({ id: 'two-factor' })) }));
// OLO-10.12: auth.ts registers customSession; stub it and the session-shape module so importing the
// instance does not pull the tenant-derivation deps (next/headers, membership store).
jest.mock('better-auth/plugins', () => ({ customSession: jest.fn((fn: unknown) => ({ id: 'custom-session', fn })) }));
// OLO-10.13: auth.ts registers the one-time-code sign-in plugin; stub it so importing the instance does
// not pull its ESM endpoint deps (better-auth/api, better-auth/cookies) or the DB module.
jest.mock('@lib/auth/better-auth-one-time-code', () => ({
  oneTimeCodePlugin: jest.fn(() => ({ id: 'one-time-code' })),
  ONE_TIME_CODE_VERIFY_PATH: '/one-time-code/verify',
}));
jest.mock('@lib/auth/better-auth-session-shape', () => ({ augmentBetterAuthUser: jest.fn() }));
jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
  APIError: class APIError extends Error {},
}));
jest.mock('@lib/db/db', () => ({ query: jest.fn() }));
// The resolver reads REST_API_BASE_URL to reach the service-token-gated resolved endpoint; stub it so
// the mocked `fetch` is the only network surface.
jest.mock('@lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: () => ({ 'Content-Type': 'application/json' }),
}));

const mockFetch = jest.fn<Promise<unknown>, unknown[]>();
(global as { fetch?: unknown }).fetch = mockFetch;

/** Service token present ⇒ the resolver reaches out to the resolved endpoint. */
const TOKEN_ENV = { INTERNAL_SERVICE_TOKEN: 'svc-token' };
/** github fully configured via env; the baseline DB config is layered over. */
const GITHUB_ENV = { GITHUB_ID: 'env-gh-id', GITHUB_SECRET: 'env-gh-secret' };

/** A distinct `now` per call keeps each assertion on a fresh resolver cache window. */
let clock = 0;
function nextNow(): number {
  clock += 100_000;
  return clock;
}

/** Build a 200 response whose JSON body is the given resolved payload. */
function okResponse(providers: Record<string, unknown>) {
  return { ok: true, status: 200, json: async () => ({ providers }) };
}

/** One resolved-config entry, all fields explicit so a test states exactly what the DB stores. */
function providerRow(overrides: Record<string, unknown>) {
  return { enabled: null, client_id: null, client_secret: null, config: {}, ...overrides };
}

/** One provider entry in a built generic-OAuth config, as far as these tests inspect it. */
interface OAuthConfigEntry {
  providerId: string;
  clientId: string;
  clientSecret: string;
}

/** The generic-OAuth config the most recently built instance was constructed with. */
function latestOAuthConfig(): OAuthConfigEntry[] {
  const calls = mockGenericOAuth.mock.calls;
  if (calls.length === 0) throw new Error('genericOAuth was never called');
  return (calls[calls.length - 1][0] as { config: OAuthConfigEntry[] }).config;
}

/** Provider ids in the most recently built instance's provider set, for membership assertions. */
function latestProviderIds(): string[] {
  return latestOAuthConfig().map((config) => config.providerId);
}

/** Load a fresh copy of the module graph (so the instance cache starts from its module-load seed). */
async function loadFresh() {
  const authModule = await import('@lib/auth/auth');
  const resolverModule = await import('@lib/auth/provider-config-resolver');
  return {
    resolveRequestAuthInstance: authModule.resolveRequestAuthInstance,
    invalidateProviderConfigCache: resolverModule.invalidateProviderConfigCache,
  };
}

beforeEach(() => {
  jest.resetModules();
  jest.clearAllMocks();
  // The degrade-to-env paths log an operator warning/error by design; silence them so the suite stays
  // clean while still asserting the fallback behaviour.
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('resolveRequestAuthInstance — DB config lands without env', () => {
  it('enables a provider from DB config even when its env pair is unset', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    // No gitlab env, but the DB supplies its credentials ⇒ gitlab becomes enabled.
    mockFetch.mockResolvedValue(
      okResponse({
        gitlab: providerRow({ client_id: 'db-gl-id', client_secret: 'db-gl-secret' }),
      })
    );

    await resolveRequestAuthInstance({ ...TOKEN_ENV }, nextNow());

    expect(latestProviderIds()).toEqual(['gitlab']);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('pins an env-configured provider off when the DB sets enabled=false', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    // github is fully configured via env, but the operator turned it off in the DB.
    mockFetch.mockResolvedValue(
      okResponse({ github: providerRow({ enabled: false }) })
    );

    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());

    expect(latestProviderIds()).toEqual([]);
  });

  it('overrides the env client id/secret with the DB values', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    mockFetch.mockResolvedValue(
      okResponse({
        github: providerRow({ client_id: 'db-gh-id', client_secret: 'db-gh-secret' }),
      })
    );

    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());

    const github = latestOAuthConfig().find((config) => config.providerId === 'github');
    expect(github).toMatchObject({ clientId: 'db-gh-id', clientSecret: 'db-gh-secret' });
  });

  it('makes google DB-overridable (added to the resolver cred map in OLO-10.8)', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    // google has no env pair here; only the DB configures it.
    mockFetch.mockResolvedValue(
      okResponse({
        google: providerRow({ client_id: 'db-goog-id', client_secret: 'db-goog-secret' }),
      })
    );

    await resolveRequestAuthInstance({ ...TOKEN_ENV }, nextNow());

    const google = latestOAuthConfig().find((config) => config.providerId === 'google');
    expect(google).toMatchObject({ clientId: 'db-goog-id', clientSecret: 'db-goog-secret' });
  });
});

describe('resolveRequestAuthInstance — env baseline preserved', () => {
  it('keeps env-only providers when no service token is set (no DB read attempted)', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();

    await resolveRequestAuthInstance({ ...GITHUB_ENV }, nextNow());

    expect(latestProviderIds()).toEqual(['github']);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('leaves an env provider untouched when the DB stores nothing for it', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    mockFetch.mockResolvedValue(okResponse({}));

    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());

    expect(latestProviderIds()).toEqual(['github']);
  });
});

describe('resolveRequestAuthInstance — DB outage degrades to env, never to a login outage', () => {
  it('falls back to the env provider set when the resolved endpoint 503s', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    mockFetch.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) });

    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());

    expect(latestProviderIds()).toEqual(['github']);
  });

  it('falls back to the env provider set on a network error and never throws', async () => {
    const { resolveRequestAuthInstance } = await loadFresh();
    mockFetch.mockRejectedValue(new Error('ECONNREFUSED'));

    await expect(
      resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow())
    ).resolves.toBeDefined();

    expect(latestProviderIds()).toEqual(['github']);
  });
});

describe('resolveRequestAuthInstance — instance caching by provider-config fingerprint', () => {
  it('reuses the instance when the resolved config is unchanged and rebuilds when it changes', async () => {
    const { resolveRequestAuthInstance, invalidateProviderConfigCache } = await loadFresh();
    // Ignore the module-load build of the static instance; count only per-request builds.
    mockBetterAuth.mockClear();

    mockFetch.mockResolvedValue(
      okResponse({
        github: providerRow({ client_id: 'db-gh-id', client_secret: 'db-gh-secret' }),
      })
    );

    // First request builds an instance for this (new) config.
    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());
    expect(mockBetterAuth).toHaveBeenCalledTimes(1);

    // Second request with the same config (fresh resolver window, same DB response) reuses it.
    invalidateProviderConfigCache();
    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());
    expect(mockBetterAuth).toHaveBeenCalledTimes(1);

    // An admin edit (a different secret) shifts the fingerprint ⇒ the next request rebuilds.
    invalidateProviderConfigCache();
    mockFetch.mockResolvedValue(
      okResponse({
        github: providerRow({ client_id: 'db-gh-id', client_secret: 'rotated-secret' }),
      })
    );
    await resolveRequestAuthInstance({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow());
    expect(mockBetterAuth).toHaveBeenCalledTimes(2);

    const github = latestOAuthConfig().find((config) => config.providerId === 'github');
    expect(github).toMatchObject({ clientSecret: 'rotated-secret' });
  });
});
