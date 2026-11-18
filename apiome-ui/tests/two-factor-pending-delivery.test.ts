/**
 * @jest-environment node
 *
 * Where a pending sign-in's one-time code will go, read from the `two_factor` cookie (OLO-9.51 #5071).
 */

const mockMakeSignature = jest.fn(async () => 'S'.repeat(43) + '=');
const mockConstantTimeEqual = jest.fn((a: string, b: string) => a === b);

jest.mock('next/headers', () => ({ cookies: jest.fn() }));
jest.mock('@lib/auth/better-auth-session', () => ({ resolveBetterAuthSecret: () => 'secret' }));
jest.mock('better-auth/crypto', () => ({
  makeSignature: (...args: unknown[]) => mockMakeSignature(...(args as [])),
  constantTimeEqual: (a: string, b: string) => mockConstantTimeEqual(a, b),
}));
jest.mock('@lib/auth/sms-otp-config', () => ({ isTwoFactorSmsOtpConfigured: () => true }));
jest.mock('@lib/auth/send-two-factor-email-otp', () => ({
  isTwoFactorEmailOtpConfigured: () => true,
}));
jest.mock('@lib/db/db', () => ({ query: jest.fn() }));

import { getPendingOtpDelivery } from '@lib/auth/two-factor-pending-delivery';
import { TWO_FACTOR_COOKIE_NAMES } from '@lib/auth/two-factor-trust-cookie';

const SIGNED = `challenge-id.${'S'.repeat(43)}=`;
const SMS_ROW = { channel: 'sms', phoneNumber: '+14155550123', phoneNumberVerified: true };

describe('getPendingOtpDelivery', () => {
  beforeEach(() => {
    jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  });
  afterEach(() => jest.restoreAllMocks());

  it('reads both cookie name variants', () => {
    expect(TWO_FACTOR_COOKIE_NAMES).toEqual([
      'better-auth.two_factor',
      '__Secure-better-auth.two_factor',
    ]);
  });

  it('resolves the challenged user and describes their SMS delivery', async () => {
    const readUser = jest.fn(async () => 'u1');
    const readRow = jest.fn(async () => SMS_ROW);
    await expect(
      getPendingOtpDelivery({
        readCookie: async () => SIGNED,
        readUser,
        readRow,
        secret: 'secret',
      }),
    ).resolves.toEqual({ channel: 'sms', destination: '•••• 0123', available: true });
    expect(readUser).toHaveBeenCalledWith('challenge-id');
    expect(readRow).toHaveBeenCalledWith('u1');
  });

  it('answers null without a cookie', async () => {
    await expect(
      getPendingOtpDelivery({ readCookie: async () => null, secret: 'secret' }),
    ).resolves.toBeNull();
  });

  it('answers null for a forged signature, without looking anyone up', async () => {
    const readUser = jest.fn(async () => 'u1');
    await expect(
      getPendingOtpDelivery({
        readCookie: async () => `challenge-id.${'X'.repeat(43)}=`,
        readUser,
        secret: 'secret',
      }),
    ).resolves.toBeNull();
    expect(readUser).not.toHaveBeenCalled();
  });

  it('answers null for an expired challenge', async () => {
    await expect(
      getPendingOtpDelivery({
        readCookie: async () => SIGNED,
        readUser: async () => null,
        secret: 'secret',
      }),
    ).resolves.toBeNull();
  });

  it('answers null when a lookup throws', async () => {
    await expect(
      getPendingOtpDelivery({
        readCookie: async () => SIGNED,
        readUser: async () => {
          throw new Error('db down');
        },
        secret: 'secret',
      }),
    ).resolves.toBeNull();
  });
});
