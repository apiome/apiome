/**
 * @jest-environment node
 *
 * Linked-account tokens are sealed where they are stored (OLO-7.3 follow-up, #4960).
 *
 * Drives the `lib/db` helpers through a mocked connection pool with the **real** token codec, and
 * asserts what actually reaches SQL and what comes back:
 *
 * - linking an account and saving a PAT bind ciphertext, never the token;
 * - with no encryption key, linking stores no token and a PAT is refused — nothing is written in
 *   plaintext;
 * - the readers hand server-side callers the plaintext token, and the panel only a six-character
 *   suffix (sealed and legacy plaintext rows alike);
 * - a staged OAuth sign-up seals its token set and restores it on read.
 */
import { randomBytes } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

import { KEYS_SETTING, isSealed, sealToken, unsealToken } from '../lib/auth/linked-account-token-crypto';

jest.mock('../lib/db/db', () => ({ query: jest.fn(), connect: jest.fn() }));
jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn() }));
jest.mock('../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));
jest.mock('../lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => ({ user: { user_id: 'user-1' } })),
}));

const USER = 'user-1';
const ACCOUNT = 'acct-1';
const ACCESS = 'gho_test_access_token_not_real_ABCDEF';
const REFRESH = 'ghr_test_refresh_token_not_real_UVWXYZ';
const PAT = 'ghp_test_pat_not_a_real_credential_123456';

/** The shape every mocked query resolves to. */
type QueryResult = { rowCount: number; rows: Record<string, unknown>[] };

const pool = jest.requireMock('../lib/db/db') as {
  query: jest.Mock<(sql: string, params?: unknown[]) => Promise<QueryResult>>;
};

/** Every bound parameter of every statement the helper under test ran. */
const boundParams = () => pool.query.mock.calls.flatMap(([, params]) => params ?? []);

/** The parameters of the first statement matching `pattern`. */
const paramsOf = (pattern: RegExp) =>
  (pool.query.mock.calls.find(([sql]) => pattern.test(sql)) ?? [])[1] as unknown[] | undefined;

const savedKeys = process.env[KEYS_SETTING];
let warn: ReturnType<typeof jest.spyOn>;

/** Configure a fresh master key for the test. */
const configureEncryption = () => {
  process.env[KEYS_SETTING] = JSON.stringify({ '1': randomBytes(32).toString('base64') });
};

beforeEach(() => {
  pool.query.mockReset();
  configureEncryption();
  warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  warn.mockRestore();
  if (savedKeys === undefined) delete process.env[KEYS_SETTING];
  else process.env[KEYS_SETTING] = savedKeys;
});

describe('linkExternalAccount', () => {
  /** Answer the two uniqueness probes with "free", then the INSERT. */
  const mockLinkQueries = () =>
    pool.query.mockImplementation(async (sql: string) =>
      /INSERT INTO apiome\.external_auth_providers/.test(sql)
        ? { rowCount: 1, rows: [{ id: ACCOUNT, provider: 'github' }] }
        : { rowCount: 0, rows: [] }
    );

  const link = async (access: string | null = ACCESS, refresh: string | null = REFRESH) => {
    const { linkExternalAccount } = await import('../lib/db/helper');
    return JSON.parse(
      await linkExternalAccount(USER, 'github', 'gh-1', 'a@example.com', 'octo', access, refresh, null, null, true)
    );
  };

  test('binds sealed tokens, never the plaintext', async () => {
    mockLinkQueries();
    expect((await link()).success).toBe(true);

    const params = paramsOf(/INSERT INTO apiome\.external_auth_providers/) as unknown[];
    const [sealedAccess, sealedRefresh] = [params[6], params[7]];
    expect(isSealed(sealedAccess)).toBe(true);
    expect(isSealed(sealedRefresh)).toBe(true);
    expect(unsealToken(sealedAccess)).toBe(ACCESS);
    expect(unsealToken(sealedRefresh)).toBe(REFRESH);
    expect(boundParams()).not.toContain(ACCESS);
    expect(boundParams()).not.toContain(REFRESH);
  });

  test('still links, storing no token, when encryption is not configured', async () => {
    delete process.env[KEYS_SETTING];
    mockLinkQueries();
    expect((await link()).success).toBe(true);

    const params = paramsOf(/INSERT INTO apiome\.external_auth_providers/) as unknown[];
    expect(params[6]).toBeNull();
    expect(params[7]).toBeNull();
    expect(boundParams()).not.toContain(ACCESS);
    expect(boundParams()).not.toContain(REFRESH);
  });

  test('stores NULL when the provider issued no token', async () => {
    mockLinkQueries();
    await link(null, null);
    const params = paramsOf(/INSERT INTO apiome\.external_auth_providers/) as unknown[];
    expect(params[6]).toBeNull();
    expect(params[7]).toBeNull();
  });
});

describe.each(['addPersonalAccessToken', 'updatePersonalAccessToken'] as const)('%s', (name) => {
  const save = async (token = PAT) => {
    const helper = await import('../lib/db/helper');
    return JSON.parse(await helper[name](USER, ACCOUNT, token));
  };

  test('binds a sealed token, never the plaintext', async () => {
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: ACCOUNT, provider: 'github' }] });
    expect((await save()).success).toBe(true);

    const params = paramsOf(/UPDATE apiome\.external_auth_providers/) as unknown[];
    expect(isSealed(params[0])).toBe(true);
    expect(unsealToken(params[0])).toBe(PAT);
    expect(boundParams()).not.toContain(PAT);
  });

  test('is refused, writing nothing, when encryption is not configured', async () => {
    delete process.env[KEYS_SETTING];
    const result = await save();
    expect(result.success).toBe(false);
    expect(result.error).toContain(KEYS_SETTING);
    expect(result.error).not.toContain(PAT);
    expect(pool.query).not.toHaveBeenCalled();
  });

  test('is refused for an empty token', async () => {
    const result = await save('');
    expect(result.success).toBe(false);
    expect(pool.query).not.toHaveBeenCalled();
  });
});

describe('readers', () => {
  test('getLinkedAccountsForUser returns only a six-character suffix', async () => {
    pool.query.mockResolvedValue({
      rowCount: 3,
      rows: [
        { id: 'a', provider: 'github', access_token: sealToken(PAT) },
        { id: 'b', provider: 'gitlab', access_token: 'legacy-plaintext-token-LEGACY' },
        { id: 'c', provider: 'google', access_token: null },
      ],
    });
    const { getLinkedAccountsForUser } = await import('../lib/db/helper');
    const raw = await getLinkedAccountsForUser(USER);
    const rows = JSON.parse(raw) as Record<string, unknown>[];

    expect(rows.map((row) => row.access_token_suffix)).toEqual(['123456', 'LEGACY', null]);
    expect(rows.every((row) => !('access_token' in row))).toBe(true);
    expect(raw).not.toContain(PAT);
    expect(raw).not.toContain('enc:v1:');
    // The suffix is cut after unsealing, not by SQL over the ciphertext.
    expect(pool.query.mock.calls[0][0]).not.toMatch(/RIGHT\(access_token/);
  });

  test('getLinkedAccountsForUser shows no suffix for a token that cannot be opened', async () => {
    const sealed = sealToken(PAT);
    configureEncryption(); // the key that sealed it is gone
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: 'a', provider: 'github', access_token: sealed }] });
    const { getLinkedAccountsForUser } = await import('../lib/db/helper');
    expect(JSON.parse(await getLinkedAccountsForUser(USER))[0].access_token_suffix).toBeNull();
  });

  test.each(['getLinkedAccountById', 'getLinkedAccountByProviderForUser'] as const)(
    '%s returns the plaintext tokens for server-side provider calls',
    async (name) => {
      pool.query.mockResolvedValue({
        rowCount: 1,
        rows: [{ id: ACCOUNT, provider: 'github', access_token: sealToken(ACCESS), refresh_token: sealToken(REFRESH) }],
      });
      const helper = await import('../lib/db/helper');
      const parsed = JSON.parse(
        name === 'getLinkedAccountById' ? await helper[name](ACCOUNT, USER) : await helper[name](USER, 'github')
      );
      expect(parsed.found).toBe(true);
      expect(parsed.account.access_token).toBe(ACCESS);
      expect(parsed.account.refresh_token).toBe(REFRESH);
    }
  );

  test('getLinkedAccountById reads a legacy plaintext row and hides an unreadable one', async () => {
    const { getLinkedAccountById } = await import('../lib/db/helper');
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: ACCOUNT, access_token: ACCESS, refresh_token: null }] });
    expect(JSON.parse(await getLinkedAccountById(ACCOUNT, USER)).account.access_token).toBe(ACCESS);

    const sealed = sealToken(ACCESS);
    delete process.env[KEYS_SETTING];
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: ACCOUNT, access_token: sealed, refresh_token: null }] });
    expect(JSON.parse(await getLinkedAccountById(ACCOUNT, USER)).account.access_token).toBeNull();
  });

  test('getLinkedAccountByProvider no longer reads the token columns at all', async () => {
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: ACCOUNT, user_id: USER }] });
    const { getLinkedAccountByProvider } = await import('../lib/db/helper');
    expect(JSON.parse(await getLinkedAccountByProvider('github', 'gh-1')).account.user_id).toBe(USER);
    expect(pool.query.mock.calls[0][0]).not.toMatch(/access_token|refresh_token/);
  });
});

describe('staged OAuth sign-up (oauth_signup_pending)', () => {
  const account = {
    provider: 'github',
    access_token: ACCESS,
    refresh_token: REFRESH,
    id_token: 'eyJ.test-id-token.not-real',
    expires_at: 1900000000,
    scope: 'read:user',
  };

  test('seals the token set on write and restores it on read', async () => {
    const { upsertOauthSignupPending, getOauthSignupPendingById } = await import('../lib/db/oauth-signup');
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: 'pending-1' }] });
    await upsertOauthSignupPending('github', 'gh-1', 'a@example.com', account, { login: 'octo' });

    const [, params] = pool.query.mock.calls[0];
    const storedJson = (params as unknown[])[3] as string;
    for (const secret of [ACCESS, REFRESH, account.id_token]) expect(storedJson).not.toContain(secret);
    const stored = JSON.parse(storedJson);
    for (const field of ['access_token', 'refresh_token', 'id_token']) expect(isSealed(stored[field])).toBe(true);
    // Non-secret fields are stored as they were.
    expect(stored).toMatchObject({ provider: 'github', expires_at: 1900000000, scope: 'read:user' });

    pool.query.mockResolvedValue({
      rowCount: 1,
      rows: [{ id: 'pending-1', account_json: stored, profile_json: {}, expires_at: new Date(Date.now() + 60_000) }],
    });
    const pending = await getOauthSignupPendingById('pending-1');
    expect(pending?.account_json).toEqual(account);
  });

  test('stages no token — not plaintext — when encryption is not configured', async () => {
    delete process.env[KEYS_SETTING];
    const { upsertOauthSignupPending } = await import('../lib/db/oauth-signup');
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: 'pending-1' }] });
    await upsertOauthSignupPending('github', 'gh-1', 'a@example.com', account, {});

    const storedJson = (pool.query.mock.calls[0][1] as unknown[])[3] as string;
    for (const secret of [ACCESS, REFRESH, account.id_token]) expect(storedJson).not.toContain(secret);
    expect(JSON.parse(storedJson)).toMatchObject({ access_token: null, refresh_token: null, id_token: null });
  });

  test('leaves an account without token fields untouched', async () => {
    const { upsertOauthSignupPending } = await import('../lib/db/oauth-signup');
    pool.query.mockResolvedValue({ rowCount: 1, rows: [{ id: 'pending-1' }] });
    await upsertOauthSignupPending('github', 'gh-1', 'a@example.com', { provider: 'github' }, {});
    expect(JSON.parse((pool.query.mock.calls[0][1] as unknown[])[3] as string)).toEqual({ provider: 'github' });
  });
});
