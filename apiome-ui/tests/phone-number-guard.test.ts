/**
 * @jest-environment node
 *
 * The phoneNumber plugin narrowed to "verify a number on my own account" (OLO-9.51 #5071).
 */

jest.mock('better-auth/api', () => ({
  getAuthoritativeSessionFromCtx: jest.fn(),
  APIError: class APIError extends Error {
    status: string;
    body: { message?: string; code?: string };
    constructor(status: string, body: { message?: string; code?: string } = {}) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

import {
  DISABLED_PHONE_NUMBER_PATHS,
  PHONE_NUMBER_GUARD_CODES,
  phoneNumberGuardHandler,
} from '@lib/auth/phone-number-guard';

const ENV = {
  TWILIO_ACCOUNT_SID: 'AC1',
  TWILIO_AUTH_TOKEN: 't',
  TWILIO_FROM_NUMBER: '+15005550006',
};
const signedIn = jest.fn(async () => ({ user: { id: 'u1' } }));
const signedOut = jest.fn(async () => null);

/** Run the guard and return the thrown error's status + code (or `null` when it passed). */
async function outcome(
  ctx: Record<string, unknown>,
  readSession = signedIn,
  env: NodeJS.Dict<string> = ENV,
): Promise<{ status: string; code?: string } | null> {
  try {
    await phoneNumberGuardHandler(ctx, readSession, env);
    return null;
  } catch (error) {
    const e = error as { status: string; body: { code?: string } };
    return { status: e.status, code: e.body.code };
  }
}

describe('phoneNumberGuardHandler', () => {
  it('switches off sign-in and reset by phone', () => {
    expect(DISABLED_PHONE_NUMBER_PATHS).toEqual([
      '/sign-in/phone-number',
      '/phone-number/request-password-reset',
      '/phone-number/reset-password',
    ]);
  });

  it('ignores every other path', async () => {
    expect(await outcome({ path: '/sign-in/email', body: {} }, signedOut, {})).toBeNull();
    expect(await outcome({ path: '/get-session' }, signedOut, {})).toBeNull();
  });

  it('refuses an unverified number on any other route, such as sign-up', async () => {
    expect(
      await outcome(
        { path: '/sign-up/email', body: { email: 'a@b.c', phoneNumber: '+14155550123' } },
        signedOut,
      ),
    ).toEqual({ status: 'BAD_REQUEST', code: PHONE_NUMBER_GUARD_CODES.verifyOnly });
    expect(await outcome({ path: '/update-user', body: { phoneNumber: '+14155550123' } })).toEqual({
      status: 'BAD_REQUEST',
      code: PHONE_NUMBER_GUARD_CODES.verifyOnly,
    });
  });

  it('lets update-user clear the number', async () => {
    expect(await outcome({ path: '/update-user', body: { phoneNumber: null } })).toBeNull();
  });

  it('lets a signed-in user send a code to an E.164 number', async () => {
    expect(
      await outcome({ path: '/phone-number/send-otp', body: { phoneNumber: '+14155550123' } }),
    ).toBeNull();
  });

  it('lets a signed-in user verify in updatePhoneNumber mode', async () => {
    expect(
      await outcome({
        path: '/phone-number/verify',
        body: { phoneNumber: '+14155550123', code: '123456', updatePhoneNumber: true },
      }),
    ).toBeNull();
  });

  it('refuses verify without updatePhoneNumber — that would sign in by phone', async () => {
    expect(
      await outcome({
        path: '/phone-number/verify',
        body: { phoneNumber: '+14155550123', code: '123456' },
      }),
    ).toEqual({ status: 'BAD_REQUEST', code: PHONE_NUMBER_GUARD_CODES.updateOnly });
  });

  it('refuses an unauthenticated send (no texting arbitrary numbers)', async () => {
    expect(
      await outcome(
        { path: '/phone-number/send-otp', body: { phoneNumber: '+14155550123' } },
        signedOut,
      ),
    ).toEqual({ status: 'UNAUTHORIZED', code: PHONE_NUMBER_GUARD_CODES.signInRequired });
  });

  it('refuses a number without a country code', async () => {
    expect(
      await outcome({ path: '/phone-number/send-otp', body: { phoneNumber: '4155550123' } }),
    ).toEqual({
      status: 'BAD_REQUEST',
      code: PHONE_NUMBER_GUARD_CODES.invalidNumber,
    });
  });

  it('refuses both routes when SMS is not configured', async () => {
    expect(
      await outcome(
        { path: '/phone-number/send-otp', body: { phoneNumber: '+14155550123' } },
        signedIn,
        {},
      ),
    ).toEqual({ status: 'BAD_REQUEST', code: PHONE_NUMBER_GUARD_CODES.notConfigured });
  });
});
