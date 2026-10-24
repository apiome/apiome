/**
 * Cached read of the installation sign-up policy (SGN-1.4, #5653).
 *
 * Mirrors the cache half of `apiome-rest/tests/test_signup_policy.py`: env fallback when nothing
 * is stored, the stored policy winning over env, a change landing after the cache lifetime without
 * a restart, invalidation applying it at once, and failing closed when the database is unreadable.
 */
const mockQuery = jest.fn();
jest.mock('../lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));

import {
  DEFAULT_CACHE_TTL_MS,
  MAX_CACHE_TTL_MS,
  MIN_CACHE_TTL_MS,
  invalidateSignupPolicyCache,
  resolveSignupPolicy,
  signupPolicyCacheTtlMs,
} from '../lib/auth/signup-policy-resolver';

beforeEach(() => {
  invalidateSignupPolicyCache();
  mockQuery.mockReset();
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('resolveSignupPolicy', () => {
  test.each([
    ['true', 'closed'],
    [undefined, 'open'],
  ])('unset in the database leaves env behaviour unchanged (%j → %s)', async (value, mode) => {
    const resolved = await resolveSignupPolicy({
      readRow: async () => null,
      env: { AUTH_SIGNUP_DISABLED: value },
    });
    expect(resolved).toEqual({ mode, allowedEmailDomains: [], source: 'env', blockedEmailDomains: [] });
  });

  test('a stored policy wins over env', async () => {
    const resolved = await resolveSignupPolicy({
      readRow: async () => ({ mode: 'invite_only', allowed_email_domains: [] }),
      env: { AUTH_SIGNUP_DISABLED: 'true' },
    });
    expect(resolved).toEqual({
      mode: 'invite_only',
      allowedEmailDomains: [],
      source: 'db',
      blockedEmailDomains: [],
    });
  });

  test('a change takes effect after the cache lifetime, without a restart', async () => {
    let clock = 1_000;
    const stored = { mode: 'open', allowed_email_domains: [] as string[] };
    const readRow = jest.fn(async () => ({ ...stored }));
    const resolve = () => resolveSignupPolicy({ readRow, env: {}, now: () => clock });

    expect((await resolve()).mode).toBe('open');
    stored.mode = 'closed';
    clock += DEFAULT_CACHE_TTL_MS - 1;
    expect((await resolve()).mode).toBe('open');
    expect(readRow).toHaveBeenCalledTimes(1);
    clock += 2;
    expect((await resolve()).mode).toBe('closed');
    expect(readRow).toHaveBeenCalledTimes(2);
  });

  test('invalidation applies a change at once', async () => {
    const stored = { mode: 'open', allowed_email_domains: [] as string[] };
    const resolve = () => resolveSignupPolicy({ readRow: async () => ({ ...stored }), env: {} });

    expect((await resolve()).mode).toBe('open');
    stored.mode = 'closed';
    invalidateSignupPolicyCache();
    expect((await resolve()).mode).toBe('closed');
  });

  test('an unreadable database fails closed, and the failure is not cached', async () => {
    const broken = async () => {
      throw new Error('db down');
    };
    expect((await resolveSignupPolicy({ readRow: broken, env: {} })).mode).toBe('closed');
    expect((await resolveSignupPolicy({ readRow: async () => null, env: {} })).mode).toBe('open');
  });

  test('an unreadable database serves the last known policy', async () => {
    let clock = 0;
    await resolveSignupPolicy({
      readRow: async () => ({ mode: 'invite_only', allowed_email_domains: [] }),
      env: {},
      now: () => clock,
    });
    clock += MAX_CACHE_TTL_MS + 1;
    const resolved = await resolveSignupPolicy({
      readRow: async () => {
        throw new Error('db down');
      },
      env: {},
      now: () => clock,
    });
    expect(resolved.mode).toBe('invite_only');
  });
});

describe('the default database read', () => {
  test('selects the singleton row', async () => {
    mockQuery.mockResolvedValue({
      rowCount: 1,
      rows: [{ mode: 'closed', allowed_email_domains: [] }],
    });
    expect((await resolveSignupPolicy({ env: {} })).mode).toBe('closed');
    expect(mockQuery.mock.calls[0][0]).toContain('FROM apiome.signup_policy');
  });

  test('reads the blocklist once V317 is applied, and none before it (SGN-1.5)', async () => {
    // `SELECT *`: a pre-V317 row simply has no blocked_email_domains column.
    mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ mode: 'open', allowed_email_domains: [] }] });
    expect((await resolveSignupPolicy({ env: {} })).blockedEmailDomains).toEqual([]);
    expect(mockQuery.mock.calls[0][0]).toContain('SELECT *');
  });

  test('no row falls back to env', async () => {
    mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });
    expect(await resolveSignupPolicy({ env: {} })).toEqual({
      mode: 'open',
      allowedEmailDomains: [],
      source: 'env',
      blockedEmailDomains: [],
    });
  });

  test('a database without the table yet (V274 not applied) falls back to env', async () => {
    mockQuery.mockRejectedValue(
      Object.assign(new Error('relation does not exist'), { code: '42P01' }),
    );
    expect((await resolveSignupPolicy({ env: { AUTH_SIGNUP_DISABLED: '1' } })).source).toBe('env');
  });

  test('any other database error fails closed', async () => {
    mockQuery.mockRejectedValue(Object.assign(new Error('connection refused'), { code: '08006' }));
    expect(await resolveSignupPolicy({ env: {} })).toEqual({
      mode: 'closed',
      allowedEmailDomains: [],
      source: 'db',
    });
  });
});

describe('signupPolicyCacheTtlMs', () => {
  test.each([
    [undefined, DEFAULT_CACHE_TTL_MS],
    ['', DEFAULT_CACHE_TTL_MS],
    ['abc', DEFAULT_CACHE_TTL_MS],
    ['10', 10_000],
    ['0', MIN_CACHE_TTL_MS],
    ['99999', MAX_CACHE_TTL_MS],
  ])('SIGNUP_POLICY_CACHE_TTL_SECONDS=%j → %d ms', (raw, expected) => {
    expect(signupPolicyCacheTtlMs({ SIGNUP_POLICY_CACHE_TTL_SECONDS: raw })).toBe(expected);
  });
});
