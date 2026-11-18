/**
 * @jest-environment node
 *
 * Twilio SMS delivery for two-factor codes and phone verification (OLO-9.51 #5071).
 */

jest.mock('better-auth/api', () => ({
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
  SMS_MAX_PER_HOUR,
  SMS_RATE_LIMITED_CODE,
  SMS_SEND_COOLDOWN_SECONDS,
  isTwoFactorSmsOtpConfigured,
  reserveSmsSend,
  resetSmsSendLog,
  sendPhoneVerificationSms,
  sendSms,
  sendTwoFactorSmsOtp,
} from '@lib/auth/send-two-factor-sms-otp';

const ENV = {
  TWILIO_ACCOUNT_SID: 'AC123',
  TWILIO_AUTH_TOKEN: 'token',
  TWILIO_FROM_NUMBER: '+15005550006',
};

/** A fetch stub answering `status`, recording each call. */
function fetchStub(status = 201) {
  return jest.fn(async () => new Response('{}', { status })) as unknown as jest.Mock & typeof fetch;
}

describe('isTwoFactorSmsOtpConfigured', () => {
  it('needs the SID, the token and a sender', () => {
    expect(isTwoFactorSmsOtpConfigured(ENV)).toBe(true);
    expect(
      isTwoFactorSmsOtpConfigured({
        ...ENV,
        TWILIO_FROM_NUMBER: '',
        TWILIO_MESSAGING_SERVICE_SID: 'MG1',
      }),
    ).toBe(true);
    expect(isTwoFactorSmsOtpConfigured({ ...ENV, TWILIO_AUTH_TOKEN: '  ' })).toBe(false);
    expect(isTwoFactorSmsOtpConfigured({ ...ENV, TWILIO_ACCOUNT_SID: undefined })).toBe(false);
    expect(isTwoFactorSmsOtpConfigured({ ...ENV, TWILIO_FROM_NUMBER: undefined })).toBe(false);
    expect(isTwoFactorSmsOtpConfigured({})).toBe(false);
  });
});

describe('sendSms', () => {
  beforeEach(() => {
    resetSmsSendLog();
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
  });
  afterEach(() => jest.restoreAllMocks());

  it('posts the message to Twilio with basic auth and the from-number', async () => {
    const fetchImpl = fetchStub();
    await sendSms({ to: '+14155550123', body: 'hello' }, ENV, fetchImpl);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>).Authorization).toBe(
      `Basic ${Buffer.from('AC123:token').toString('base64')}`,
    );
    const form = new URLSearchParams(init.body as string);
    expect(form.get('To')).toBe('+14155550123');
    expect(form.get('From')).toBe('+15005550006');
    expect(form.get('Body')).toBe('hello');
  });

  it('prefers a Messaging Service SID over the from-number', async () => {
    const fetchImpl = fetchStub();
    await sendSms(
      { to: '+14155550123', body: 'x' },
      { ...ENV, TWILIO_MESSAGING_SERVICE_SID: 'MG9' },
      fetchImpl,
    );
    const form = new URLSearchParams(
      (fetchImpl.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(form.get('MessagingServiceSid')).toBe('MG9');
    expect(form.get('From')).toBeNull();
  });

  it('throws when Twilio is not configured, without calling it', async () => {
    const fetchImpl = fetchStub();
    await expect(sendSms({ to: '+14155550123', body: 'x' }, {}, fetchImpl)).rejects.toThrow(
      'SMS two-factor is not configured',
    );
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('refuses a number that is not E.164', async () => {
    const fetchImpl = fetchStub();
    await expect(sendSms({ to: '4155550123', body: 'x' }, ENV, fetchImpl)).rejects.toThrow(
      'invalid phone number',
    );
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('throws when Twilio refuses the message, without logging the body', async () => {
    const fetchImpl = fetchStub(400);
    await expect(
      sendSms({ to: '+14155550123', body: 'code 123456' }, ENV, fetchImpl),
    ).rejects.toThrow('Twilio send failed (400)');
    for (const call of (console.error as jest.Mock).mock.calls) {
      expect(JSON.stringify(call)).not.toContain('123456');
    }
  });
});

describe('reserveSmsSend', () => {
  beforeEach(() => resetSmsSendLog());

  it('enforces the cooldown between texts to one number', () => {
    const t0 = Date.parse('2026-11-17T10:00:00Z');
    reserveSmsSend('+14155550123', t0);
    expect(() => reserveSmsSend('+14155550123', t0 + 1000)).toThrow(
      expect.objectContaining({ body: expect.objectContaining({ code: SMS_RATE_LIMITED_CODE }) }),
    );
    // Another number is unaffected.
    expect(() => reserveSmsSend('+14155550124', t0 + 1000)).not.toThrow();
    expect(() =>
      reserveSmsSend('+14155550123', t0 + SMS_SEND_COOLDOWN_SECONDS * 1000),
    ).not.toThrow();
  });

  it('caps texts per number per hour', () => {
    const t0 = Date.parse('2026-11-17T10:00:00Z');
    const step = SMS_SEND_COOLDOWN_SECONDS * 1000;
    for (let i = 0; i < SMS_MAX_PER_HOUR; i += 1) reserveSmsSend('+14155550123', t0 + i * step);
    expect(() => reserveSmsSend('+14155550123', t0 + SMS_MAX_PER_HOUR * step)).toThrow();
    // An hour after the first send, a slot frees up.
    expect(() => reserveSmsSend('+14155550123', t0 + 60 * 60 * 1000 + 1)).not.toThrow();
  });
});

describe('message helpers', () => {
  beforeEach(() => resetSmsSendLog());

  it('texts the sign-in code', async () => {
    const fetchImpl = fetchStub();
    await sendTwoFactorSmsOtp({ phoneNumber: '+14155550123', otp: '987654' }, ENV, fetchImpl);
    const form = new URLSearchParams(
      (fetchImpl.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(form.get('Body')).toContain('Your apiome sign-in code is 987654.');
  });

  it('texts the phone verification code', async () => {
    const fetchImpl = fetchStub();
    await sendPhoneVerificationSms({ phoneNumber: '+14155550123', code: '135790' }, ENV, fetchImpl);
    const form = new URLSearchParams(
      (fetchImpl.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(form.get('Body')).toContain('phone verification code is 135790');
  });
});
