/**
 * Twilio SMS delivery for two-factor codes and phone verification (OLO-9.51 #5071).
 *
 * Two kinds of text go out through here:
 * - the **sign-in code** of a user whose two-factor codes go by SMS (Better Auth
 *   `twoFactor` `otpOptions.sendOTP`, routed by `two-factor-otp-dispatch.ts`), and
 * - the **verification code** that proves a user owns the number they are adding (Better Auth
 *   `phoneNumber` plugin `sendOTP`).
 *
 * Twilio is called over its REST API with `fetch` (no SDK dependency). Configuration is
 * env-only (`sms-otp-config.ts`); SMS is off unless `isTwoFactorSmsOtpConfigured`.
 *
 * Every send is throttled per destination number ({@link SMS_SEND_COOLDOWN_SECONDS} between
 * texts, at most {@link SMS_MAX_PER_HOUR} an hour) on top of Better Auth's own per-IP limits, so
 * a stolen password cannot be used to run up a texting bill against one number. The throttle is
 * per server process — with several replicas the effective cap is multiplied by their count.
 */

import { APIError } from 'better-auth/api';
import { isE164PhoneNumber } from './phone-number-format';
import {
  TWILIO_ACCOUNT_SID_ENV,
  TWILIO_AUTH_TOKEN_ENV,
  TWILIO_FROM_NUMBER_ENV,
  TWILIO_MESSAGING_SERVICE_SID_ENV,
  readEnv,
} from './sms-otp-config';

// Re-exported so callers that send can also ask whether sending is possible from one import.
export {
  TWILIO_ACCOUNT_SID_ENV,
  TWILIO_AUTH_TOKEN_ENV,
  TWILIO_FROM_NUMBER_ENV,
  TWILIO_MESSAGING_SERVICE_SID_ENV,
  isTwoFactorSmsOtpConfigured,
} from './sms-otp-config';

/** Minimum seconds between two texts to the same number. */
export const SMS_SEND_COOLDOWN_SECONDS = 30;

/** Most texts one number may receive in a rolling hour. */
export const SMS_MAX_PER_HOUR = 5;

/** Stable error code for a throttled send. */
export const SMS_RATE_LIMITED_CODE = 'SMS_RATE_LIMITED';

/** Twilio's REST API base. */
const TWILIO_API_BASE = 'https://api.twilio.com/2010-04-01';

/** The env map shape every function here reads. */
type Env = NodeJS.Dict<string>;

/** Send history per destination number: epoch-ms timestamps of the last hour's texts. */
const sendLog = new Map<string, number[]>();

/**
 * Record a send to `to`, or refuse it when the number is being texted too often.
 *
 * @param to Destination number.
 * @param now Current epoch ms (injectable for tests).
 * @throws APIError `429` with code {@link SMS_RATE_LIMITED_CODE} when the cooldown or the hourly
 *   cap would be exceeded.
 */
export function reserveSmsSend(to: string, now: number = Date.now()): void {
  const hourAgo = now - 60 * 60 * 1000;
  const recent = (sendLog.get(to) ?? []).filter((at) => at > hourAgo);
  const last = recent[recent.length - 1];
  if (
    (last !== undefined && now - last < SMS_SEND_COOLDOWN_SECONDS * 1000) ||
    recent.length >= SMS_MAX_PER_HOUR
  ) {
    sendLog.set(to, recent);
    throw new APIError('TOO_MANY_REQUESTS', {
      message: `Too many text messages to this number. Wait ${SMS_SEND_COOLDOWN_SECONDS} seconds and try again; at most ${SMS_MAX_PER_HOUR} codes are sent an hour.`,
      code: SMS_RATE_LIMITED_CODE,
    });
  }
  recent.push(now);
  sendLog.set(to, recent);
}

/** Forget every recorded send (tests only). */
export function resetSmsSendLog(): void {
  sendLog.clear();
}

/**
 * Send one text through Twilio.
 *
 * Never logs the body (it carries a code) or the full number. On failure logs a generic line and
 * throws.
 *
 * @param params.to Destination, E.164.
 * @param params.body Message text.
 * @param env Environment map; defaults to `process.env`.
 * @param fetchImpl `fetch` (injectable for tests).
 * @throws Error when Twilio is not configured, the number is not E.164, or Twilio refuses the send;
 *   APIError `429` when the number is throttled ({@link reserveSmsSend}).
 */
export async function sendSms(
  params: { to: string; body: string },
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const accountSid = readEnv(env, TWILIO_ACCOUNT_SID_ENV);
  const authToken = readEnv(env, TWILIO_AUTH_TOKEN_ENV);
  const messagingServiceSid = readEnv(env, TWILIO_MESSAGING_SERVICE_SID_ENV);
  const fromNumber = readEnv(env, TWILIO_FROM_NUMBER_ENV);
  if (!accountSid || !authToken || (!messagingServiceSid && !fromNumber)) {
    console.error('[2fa-sms-otp] Twilio is not configured');
    throw new Error('SMS two-factor is not configured');
  }
  if (!isE164PhoneNumber(params.to)) {
    console.error('[2fa-sms-otp] destination is not an E.164 number');
    throw new Error('Cannot send SMS: invalid phone number');
  }

  reserveSmsSend(params.to);

  const form = new URLSearchParams({ To: params.to, Body: params.body });
  if (messagingServiceSid) form.set('MessagingServiceSid', messagingServiceSid);
  else form.set('From', fromNumber as string);

  let response: Response;
  try {
    response = await fetchImpl(
      `${TWILIO_API_BASE}/Accounts/${encodeURIComponent(accountSid)}/Messages.json`,
      {
        method: 'POST',
        headers: {
          Authorization: `Basic ${Buffer.from(`${accountSid}:${authToken}`).toString('base64')}`,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: form.toString(),
      },
    );
  } catch (error) {
    console.error(
      '[2fa-sms-otp] Twilio request failed',
      error instanceof Error ? error.name : 'unknown',
    );
    throw error;
  }
  if (!response.ok) {
    console.error('[2fa-sms-otp] Twilio refused the message', response.status);
    throw new Error(`Twilio send failed (${response.status})`);
  }
}

/**
 * Text a two-factor sign-in code (the SMS leg of `otpOptions.sendOTP`).
 *
 * @param params.phoneNumber The user's verified number.
 * @param params.otp The 6-digit code (not logged).
 * @param env Environment map; defaults to `process.env`.
 * @param fetchImpl `fetch` (injectable for tests).
 */
export async function sendTwoFactorSmsOtp(
  params: { phoneNumber: string; otp: string },
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  await sendSms(
    {
      to: params.phoneNumber,
      body: `Your apiome sign-in code is ${params.otp}. It expires in about 3 minutes. Do not share it.`,
    },
    env,
    fetchImpl,
  );
}

/**
 * Text the code that proves a user owns the number they are adding (phoneNumber plugin `sendOTP`).
 *
 * @param params.phoneNumber The number being added.
 * @param params.code The 6-digit code (not logged).
 * @param env Environment map; defaults to `process.env`.
 * @param fetchImpl `fetch` (injectable for tests).
 */
export async function sendPhoneVerificationSms(
  params: { phoneNumber: string; code: string },
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  await sendSms(
    {
      to: params.phoneNumber,
      body: `Your apiome phone verification code is ${params.code}. It expires in 5 minutes.`,
    },
    env,
    fetchImpl,
  );
}
