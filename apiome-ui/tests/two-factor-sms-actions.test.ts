/**
 * @jest-environment node
 *
 * Profile → Security server actions for SMS two-factor (OLO-9.51 #5071).
 */

const mockGetSession = jest.fn();
const mockVerifyPassword = jest.fn();
const mockFindAccounts = jest.fn();
const mockQuery = jest.fn();
let mockSmsConfigured = true;

jest.mock('next/headers', () => ({ headers: jest.fn(async () => new Headers()) }));
jest.mock('@lib/auth/auth', () => ({
  auth: {
    api: {
      getSession: (...args: unknown[]) => mockGetSession(...args),
      verifyPassword: (...args: unknown[]) => mockVerifyPassword(...args),
    },
    $context: Promise.resolve({
      internalAdapter: { findAccounts: (...args: unknown[]) => mockFindAccounts(...args) },
    }),
  },
}));
jest.mock('@lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));
jest.mock('@lib/auth/sms-otp-config', () => ({
  isTwoFactorSmsOtpConfigured: () => mockSmsConfigured,
}));
jest.mock('@lib/auth/send-two-factor-email-otp', () => ({
  isTwoFactorEmailOtpConfigured: () => true,
}));
jest.mock('better-auth/api', () => ({
  APIError: class APIError extends Error {},
  getAuthoritativeSessionFromCtx: jest.fn(),
}));

import {
  getSmsTwoFactorStatus,
  removePhoneNumber,
  setTwoFactorOtpChannel,
} from '@lib/auth/two-factor-sms-actions';

const VERIFIED_ROW = { channel: 'email', phoneNumber: '+14155550123', phoneNumberVerified: true };
const PASSWORD_ACCOUNT = [{ providerId: 'credential', password: 'hash' }];

/** A signed-in session; `createdAt` defaults to now (fresh). */
function session(overrides: { twoFactorEnabled?: boolean; createdAt?: Date } = {}) {
  return {
    user: { id: 'u1', twoFactorEnabled: overrides.twoFactorEnabled ?? true },
    session: { createdAt: overrides.createdAt ?? new Date() },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSmsConfigured = true;
  mockGetSession.mockResolvedValue(session());
  mockFindAccounts.mockResolvedValue(PASSWORD_ACCOUNT);
  mockVerifyPassword.mockResolvedValue({ status: true });
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});
afterEach(() => jest.restoreAllMocks());

describe('getSmsTwoFactorStatus', () => {
  it('returns the masked number and stored channel', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [{ ...VERIFIED_ROW, channel: 'sms' }] });
    await expect(getSmsTwoFactorStatus()).resolves.toEqual({
      smsAvailable: true,
      emailAvailable: true,
      phoneNumber: '•••• 0123',
      channel: 'sms',
    });
  });

  it('reports no number when it is unverified', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [{ ...VERIFIED_ROW, phoneNumberVerified: false }] });
    await expect(getSmsTwoFactorStatus()).resolves.toMatchObject({
      phoneNumber: null,
      channel: 'email',
    });
  });

  it('answers null when signed out', async () => {
    mockGetSession.mockResolvedValueOnce(null);
    await expect(getSmsTwoFactorStatus()).resolves.toBeNull();
  });
});

describe('setTwoFactorOtpChannel', () => {
  it('switches to SMS after the password check', async () => {
    mockQuery
      .mockResolvedValueOnce({ rows: [VERIFIED_ROW] })
      .mockResolvedValueOnce({ rowCount: 1 });
    await expect(setTwoFactorOtpChannel({ channel: 'sms', password: 'pw' })).resolves.toEqual({
      ok: true,
    });
    expect(mockVerifyPassword).toHaveBeenCalledWith(
      expect.objectContaining({ body: { password: 'pw' } }),
    );
    const [sql, params] = mockQuery.mock.calls[1];
    expect(sql).toMatch(/SET two_factor_otp_channel = \$2/);
    expect(sql).toMatch(/"phoneNumberVerified" = true/);
    expect(params).toEqual(['u1', 'sms']);
  });

  it('blocks SMS without a verified number, before asking for the password', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [{ ...VERIFIED_ROW, phoneNumber: null }] });
    await expect(setTwoFactorOtpChannel({ channel: 'sms', password: 'pw' })).resolves.toEqual({
      ok: false,
      error: 'PHONE_NUMBER_NOT_VERIFIED',
    });
    expect(mockVerifyPassword).not.toHaveBeenCalled();
  });

  it('blocks SMS when Twilio is not configured', async () => {
    mockSmsConfigured = false;
    await expect(setTwoFactorOtpChannel({ channel: 'sms', password: 'pw' })).resolves.toEqual({
      ok: false,
      error: 'SMS_NOT_CONFIGURED',
    });
  });

  it('needs two-factor on', async () => {
    mockGetSession.mockResolvedValueOnce(session({ twoFactorEnabled: false }));
    await expect(setTwoFactorOtpChannel({ channel: 'sms', password: 'pw' })).resolves.toEqual({
      ok: false,
      error: 'TWO_FACTOR_NOT_ENABLED',
    });
  });

  it('refuses a wrong or missing password', async () => {
    mockVerifyPassword.mockRejectedValueOnce(new Error('INVALID_PASSWORD'));
    await expect(setTwoFactorOtpChannel({ channel: 'email', password: 'bad' })).resolves.toEqual({
      ok: false,
      error: 'INVALID_PASSWORD',
    });
    await expect(setTwoFactorOtpChannel({ channel: 'email' })).resolves.toEqual({
      ok: false,
      error: 'INVALID_PASSWORD',
    });
    expect(mockQuery).not.toHaveBeenCalled();
  });

  it('asks a passwordless account for a fresh sign-in instead', async () => {
    mockFindAccounts.mockResolvedValue([{ providerId: 'github' }]);
    mockGetSession.mockResolvedValueOnce(
      session({ createdAt: new Date(Date.now() - 60 * 60 * 1000) }),
    );
    await expect(setTwoFactorOtpChannel({ channel: 'email' })).resolves.toEqual({
      ok: false,
      error: 'REAUTH_REQUIRED',
    });

    mockQuery.mockResolvedValueOnce({ rowCount: 1 });
    await expect(setTwoFactorOtpChannel({ channel: 'email' })).resolves.toEqual({ ok: true });
    expect(mockVerifyPassword).not.toHaveBeenCalled();
  });

  it('refuses an unknown channel and a signed-out caller', async () => {
    await expect(setTwoFactorOtpChannel({ channel: 'pager' as never })).resolves.toEqual({
      ok: false,
      error: 'FAILED',
    });
    mockGetSession.mockResolvedValueOnce(null);
    await expect(setTwoFactorOtpChannel({ channel: 'email' })).resolves.toEqual({
      ok: false,
      error: 'UNAUTHENTICATED',
    });
  });
});

describe('removePhoneNumber', () => {
  it('clears the number and puts codes back on email', async () => {
    mockQuery.mockResolvedValueOnce({ rowCount: 1 });
    await expect(removePhoneNumber()).resolves.toEqual({ ok: true });
    const [sql, params] = mockQuery.mock.calls[0];
    expect(sql).toMatch(/"phoneNumber" = NULL/);
    expect(sql).toMatch(/two_factor_otp_channel = 'email'/);
    expect(params).toEqual(['u1']);
  });

  it('needs a session', async () => {
    mockGetSession.mockResolvedValueOnce(null);
    await expect(removePhoneNumber()).resolves.toEqual({ ok: false, error: 'UNAUTHENTICATED' });
    expect(mockQuery).not.toHaveBeenCalled();
  });
});
