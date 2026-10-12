/**
 * @jest-environment node
 *
 * The server actions behind the "your two-factor was reset" notice (TFA-1.2, #5656).
 *
 * Both are session-bound: they take no argument and act on the caller's own row, so neither can be
 * asked about — or pointed at — anybody else.
 */

const mockQuery = jest.fn();
const mockGetAuthSession = jest.fn();

jest.mock('@lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));
jest.mock('next/headers', () => ({
  cookies: jest.fn(async () => ({ get: jest.fn(), set: jest.fn() })),
  headers: jest.fn(async () => new Headers()),
}));
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: (...args: unknown[]) => mockGetAuthSession(...args),
}));
jest.mock('@lib/auth/better-auth-session', () => ({ resolveBetterAuthSecret: () => 'test-secret' }));
jest.mock('@lib/auth/cookie-options', () => ({ getSharedCookieDomain: () => undefined }));

import {
  dismissTwoFactorResetNotice,
  getTwoFactorResetNotice,
} from '@lib/auth/two-factor-profile-actions';

const RESET_AT = new Date('2026-10-12T09:00:00.000Z');

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u1' } });
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('getTwoFactorResetNotice', () => {
  it('reports an outstanding reset for the signed-in user', async () => {
    mockQuery.mockResolvedValue({ rows: [{ two_factor_reset_at: RESET_AT }] });

    expect(await getTwoFactorResetNotice()).toEqual({ resetAt: '2026-10-12T09:00:00.000Z' });

    const [sql, params] = mockQuery.mock.calls[0];
    expect(params).toEqual(['u1']);
    // Only while two-factor is still off: enrolling again ends the notice even if the stamp lingers.
    expect(sql).toContain('COALESCE("twoFactorEnabled", false) = false');
    expect(sql).toContain('deleted_at IS NULL');
  });

  it.each([
    ['no stamp', { rows: [{ two_factor_reset_at: null }] }],
    ['no row (already enrolled again, or deleted)', { rows: [] }],
  ])('reports nothing with %s', async (_name, result) => {
    mockQuery.mockResolvedValue(result);
    expect(await getTwoFactorResetNotice()).toEqual({ resetAt: null });
  });

  it('asks the database nothing when nobody is signed in', async () => {
    mockGetAuthSession.mockResolvedValue(null);
    expect(await getTwoFactorResetNotice()).toEqual({ resetAt: null });
    expect(mockQuery).not.toHaveBeenCalled();
  });

  it('reports nothing when the row cannot be read', async () => {
    mockQuery.mockRejectedValue(new Error('db down'));
    expect(await getTwoFactorResetNotice()).toEqual({ resetAt: null });
  });
});

describe('dismissTwoFactorResetNotice', () => {
  it('clears the signed-in user’s own stamp', async () => {
    mockQuery.mockResolvedValue({ rowCount: 1 });

    expect(await dismissTwoFactorResetNotice()).toEqual({ ok: true });

    const [sql, params] = mockQuery.mock.calls[0];
    expect(sql).toContain('SET two_factor_reset_at = NULL');
    expect(sql).toContain('WHERE id = $1');
    expect(params).toEqual(['u1']);
  });

  it('writes nothing when nobody is signed in', async () => {
    mockGetAuthSession.mockResolvedValue(null);
    expect(await dismissTwoFactorResetNotice()).toEqual({ ok: false });
    expect(mockQuery).not.toHaveBeenCalled();
  });

  it('reports failure when the write fails', async () => {
    mockQuery.mockRejectedValue(new Error('db down'));
    expect(await dismissTwoFactorResetNotice()).toEqual({ ok: false });
  });
});
