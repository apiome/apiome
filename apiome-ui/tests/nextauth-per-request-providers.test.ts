/**
 * Per-request OAuth provider resolution tests (OLO-8.6, #4972).
 *
 * `resolveOAuthProviders` is the per-request variant of `configuredOAuthProviders`: it resolves the
 * DB-over-env merged config (8.5) and maps the enabled set to NextAuth provider configs, so a DB
 * toggle changes the enabled provider set on the next call with no redeploy. These tests pin the
 * acceptance criteria at the seam the `[...nextauth]` handler actually calls:
 *
 *   - a DB-enabled provider not present in env appears in the resolved set,
 *   - `enabled === false` in the DB pins an env-configured provider off,
 *   - env-only providers still resolve,
 *   - every DB failure mode (no token, non-200, network error) degrades to the env provider set.
 */
jest.mock('../lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: () => ({ 'Content-Type': 'application/json' }),
}));

import { resolveOAuthProviders } from '../lib/auth/nextauth-oauth-providers';
import { invalidateProviderConfigCache } from '../lib/auth/provider-config-resolver';

const mockFetch = jest.fn<Promise<unknown>, unknown[]>();
(global as { fetch?: unknown }).fetch = mockFetch;

/** Service token present ⇒ the resolver reaches out to the resolved endpoint. */
const TOKEN_ENV = { INTERNAL_SERVICE_TOKEN: 'svc-token' };
/** github fully configured via env; used to prove DB config is layered over a real env baseline. */
const GITHUB_ENV = { GITHUB_ID: 'env-gh-id', GITHUB_SECRET: 'env-gh-secret' };

/** A distinct `now` per call keeps each assertion on a fresh cache window. */
let clock = 0;
function nextNow(): number {
  clock += 100_000;
  return clock;
}

/** Build a 200 response whose JSON body is the given resolved payload. */
function okResponse(providers: Record<string, unknown>) {
  return { ok: true, status: 200, json: async () => ({ providers }) };
}

/** Provider ids in the resolved set, for order-and-membership assertions. */
async function resolvedIds(
  baseEnv: Record<string, string | undefined>
): Promise<string[]> {
  const providers = await resolveOAuthProviders(baseEnv, nextNow());
  return providers.map((p) => p.id);
}

beforeEach(() => {
  jest.clearAllMocks();
  invalidateProviderConfigCache();
  // The degrade-to-env paths log an operator warning by design; silence it so the suite stays clean.
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('resolveOAuthProviders — DB config lands without env', () => {
  it('enables a provider from DB config even when its env pair is unset', async () => {
    // No gitlab env, but the DB supplies its credentials ⇒ gitlab becomes enabled.
    mockFetch.mockResolvedValue(
      okResponse({
        gitlab: {
          enabled: null,
          client_id: 'db-gl-id',
          client_secret: 'db-gl-secret',
          config: {},
        },
      })
    );

    expect(await resolvedIds({ ...TOKEN_ENV })).toEqual(['gitlab']);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('pins an env-configured provider off when the DB sets enabled=false', async () => {
    // github is fully configured via env, but the operator turned it off in the DB.
    mockFetch.mockResolvedValue(
      okResponse({
        github: { enabled: false, client_id: null, client_secret: null, config: {} },
      })
    );

    expect(await resolvedIds({ ...TOKEN_ENV, ...GITHUB_ENV })).toEqual([]);
  });

  it('overrides the env client id/secret with the DB values', async () => {
    mockFetch.mockResolvedValue(
      okResponse({
        github: {
          enabled: null,
          client_id: 'db-gh-id',
          client_secret: 'db-gh-secret',
          config: {},
        },
      })
    );

    const [github] = (await resolveOAuthProviders(
      { ...TOKEN_ENV, ...GITHUB_ENV },
      nextNow()
    )) as unknown as { id: string; options?: { clientId?: string; clientSecret?: string } }[];
    expect(github.id).toBe('github');
    expect(github.options).toMatchObject({ clientId: 'db-gh-id', clientSecret: 'db-gh-secret' });
  });
});

describe('resolveOAuthProviders — env baseline preserved', () => {
  it('keeps env-only providers when no service token is set (no DB read attempted)', async () => {
    expect(await resolvedIds({ ...GITHUB_ENV })).toEqual(['github']);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('leaves an env provider untouched when the DB stores nothing for it', async () => {
    mockFetch.mockResolvedValue(okResponse({}));
    expect(await resolvedIds({ ...TOKEN_ENV, ...GITHUB_ENV })).toEqual(['github']);
  });
});

describe('resolveOAuthProviders — DB outage degrades to env, never to a login outage', () => {
  it('falls back to the env provider set when the resolved endpoint 503s', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) });
    expect(await resolvedIds({ ...TOKEN_ENV, ...GITHUB_ENV })).toEqual(['github']);
  });

  it('falls back to the env provider set on a network error', async () => {
    mockFetch.mockRejectedValue(new Error('ECONNREFUSED'));
    expect(await resolvedIds({ ...TOKEN_ENV, ...GITHUB_ENV })).toEqual(['github']);
  });

  it('does not throw — a rejected fetch resolves to the env-derived providers', async () => {
    mockFetch.mockRejectedValue(new Error('boom'));
    await expect(resolveOAuthProviders({ ...TOKEN_ENV, ...GITHUB_ENV }, nextNow())).resolves.toEqual(
      expect.arrayContaining([expect.objectContaining({ id: 'github' })])
    );
  });
});
