/**
 * @jest-environment node
 *
 * Per-user routing of two-factor one-time codes to email or SMS (OLO-9.51 #5071).
 */

const mockSendEmail = jest.fn(async () => undefined);
const mockSendSms = jest.fn(async () => undefined);
const mockQuery = jest.fn();

jest.mock('@lib/auth/send-two-factor-email-otp', () => ({
  isTwoFactorEmailOtpConfigured: (env: NodeJS.Dict<string>) =>
    Boolean(env.SENDGRID_API_KEY && env.EMAIL_FROM),
  sendTwoFactorEmailOtp: (...args: unknown[]) => mockSendEmail(...(args as [])),
}));
jest.mock('@lib/auth/send-two-factor-sms-otp', () => ({
  sendTwoFactorSmsOtp: (...args: unknown[]) => mockSendSms(...(args as [])),
}));
jest.mock('@lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));

import {
  describeOtpDelivery,
  effectiveOtpChannel,
  isTwoFactorOtpConfigured,
  readOtpDeliveryRow,
  resetTwoFactorOtpChannel,
  sendTwoFactorOtp,
  type OtpDeliveryRow,
} from '@lib/auth/two-factor-otp-dispatch';

const EMAIL_ENV = { SENDGRID_API_KEY: 'SG.x', EMAIL_FROM: 'a@b.c' };
const SMS_ENV = {
  TWILIO_ACCOUNT_SID: 'AC1',
  TWILIO_AUTH_TOKEN: 't',
  TWILIO_FROM_NUMBER: '+15005550006',
};
const BOTH_ENV = { ...EMAIL_ENV, ...SMS_ENV };

const SMS_ROW: OtpDeliveryRow = {
  channel: 'sms',
  phoneNumber: '+14155550123',
  phoneNumberVerified: true,
};
const EMAIL_ROW: OtpDeliveryRow = {
  channel: 'email',
  phoneNumber: '+14155550123',
  phoneNumberVerified: true,
};
const USER = { id: 'u1', email: 'u1@example.com', name: 'U' };

beforeEach(() => jest.clearAllMocks());

describe('isTwoFactorOtpConfigured', () => {
  it('is on when either channel can deliver', () => {
    expect(isTwoFactorOtpConfigured(EMAIL_ENV)).toBe(true);
    expect(isTwoFactorOtpConfigured(SMS_ENV)).toBe(true);
    expect(isTwoFactorOtpConfigured({})).toBe(false);
  });
});

describe('effectiveOtpChannel', () => {
  it('is sms only when chosen, verified and deliverable', () => {
    expect(effectiveOtpChannel(SMS_ROW, BOTH_ENV)).toBe('sms');
  });

  it.each<[string, OtpDeliveryRow | null, NodeJS.Dict<string>]>([
    ['the user chose email', EMAIL_ROW, BOTH_ENV],
    ['the number is unverified', { ...SMS_ROW, phoneNumberVerified: false }, BOTH_ENV],
    ['there is no number', { ...SMS_ROW, phoneNumber: null }, BOTH_ENV],
    ['Twilio is not configured', SMS_ROW, EMAIL_ENV],
    ['the row is unknown', null, BOTH_ENV],
  ])('falls back to email when %s', (_label, row, env) => {
    expect(effectiveOtpChannel(row, env)).toBe('email');
  });
});

describe('describeOtpDelivery', () => {
  it('masks the number for SMS', () => {
    expect(describeOtpDelivery(SMS_ROW, BOTH_ENV)).toEqual({
      channel: 'sms',
      destination: '•••• 0123',
      available: true,
    });
  });

  it('reports email as unavailable when SendGrid is off', () => {
    expect(describeOtpDelivery(EMAIL_ROW, SMS_ENV)).toEqual({
      channel: 'email',
      destination: '',
      available: false,
    });
    expect(describeOtpDelivery(EMAIL_ROW, EMAIL_ENV).available).toBe(true);
  });
});

describe('sendTwoFactorOtp', () => {
  it('texts the code to an SMS user', async () => {
    await sendTwoFactorOtp({ user: USER, otp: '123456' }, async () => SMS_ROW, BOTH_ENV);
    expect(mockSendSms).toHaveBeenCalledWith(
      { phoneNumber: '+14155550123', otp: '123456' },
      BOTH_ENV,
    );
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  it('emails everyone else, exactly as before', async () => {
    const readRow = jest.fn(async () => EMAIL_ROW);
    await sendTwoFactorOtp({ user: USER, otp: '123456' }, readRow, BOTH_ENV);
    expect(readRow).toHaveBeenCalledWith('u1');
    expect(mockSendEmail).toHaveBeenCalledWith({ user: USER, otp: '123456' }, BOTH_ENV);
    expect(mockSendSms).not.toHaveBeenCalled();
  });

  it('emails an SMS user when Twilio is switched off', async () => {
    await sendTwoFactorOtp({ user: USER, otp: '123456' }, async () => SMS_ROW, EMAIL_ENV);
    expect(mockSendEmail).toHaveBeenCalled();
    expect(mockSendSms).not.toHaveBeenCalled();
  });
});

describe('database helpers', () => {
  it('reads the delivery row by user id', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [SMS_ROW] });
    await expect(readOtpDeliveryRow('u1')).resolves.toEqual(SMS_ROW);
    expect(mockQuery.mock.calls[0][1]).toEqual(['u1']);
    mockQuery.mockResolvedValueOnce({ rows: [] });
    await expect(readOtpDeliveryRow('missing')).resolves.toBeNull();
  });

  it('puts codes back on email', async () => {
    mockQuery.mockResolvedValueOnce({ rowCount: 1 });
    await resetTwoFactorOtpChannel('u1');
    expect(mockQuery.mock.calls[0][0]).toMatch(/SET two_factor_otp_channel = 'email'/);
    expect(mockQuery.mock.calls[0][1]).toEqual(['u1']);
  });
});
