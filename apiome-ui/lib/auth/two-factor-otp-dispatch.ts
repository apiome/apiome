/**
 * Route a two-factor one-time code to email or SMS, per user (OLO-9.51 #5071).
 *
 * Better Auth's `twoFactor` plugin has a single OTP channel (`otpOptions.sendOTP`) and treats it
 * as server-level: whenever it is registered, every `twoFactorEnabled` user is offered `"otp"`.
 * Email OTP (#5070) used that channel alone; this module puts a per-user choice in front of it.
 *
 * A user's codes go by **SMS** when all of these hold, and by **email** otherwise:
 * - they chose SMS (`users.two_factor_otp_channel = 'sms'`),
 * - they have a verified number (`"phoneNumber"` + `"phoneNumberVerified"`), and
 * - Twilio is configured.
 *
 * Falling back to email (rather than failing) when the number is gone or Twilio is switched off
 * keeps the user able to sign in; email OTP stays exactly as #5070 shipped it for everyone who
 * never chose SMS.
 */

import { isTwoFactorEmailOtpConfigured, sendTwoFactorEmailOtp } from './send-two-factor-email-otp';
import { isTwoFactorSmsOtpConfigured } from './sms-otp-config';
import { maskPhoneNumber } from './phone-number-format';

/** Where a user's two-factor codes are delivered. */
export type TwoFactorOtpChannel = 'email' | 'sms';

/** The two values `users.two_factor_otp_channel` may hold (V396 CHECK constraint). */
export const TWO_FACTOR_OTP_CHANNELS: readonly TwoFactorOtpChannel[] = ['email', 'sms'];

/** The delivery facts stored on a user row. */
export interface OtpDeliveryRow {
  /** `users.two_factor_otp_channel`. */
  channel: string | null;
  /** `users."phoneNumber"`. */
  phoneNumber: string | null;
  /** `users."phoneNumberVerified"`. */
  phoneNumberVerified: boolean | null;
}

/** Reads a user's delivery facts by id; `null` when there is no such user. */
export type OtpDeliveryReader = (userId: string) => Promise<OtpDeliveryRow | null>;

/** The user shape Better Auth passes into `otpOptions.sendOTP`. */
export interface TwoFactorOtpUser {
  id: string;
  email: string;
  name?: string | null;
}

/**
 * Whether any OTP channel can deliver, i.e. whether `otpOptions.sendOTP` should be registered.
 *
 * @param env Environment map; defaults to `process.env`.
 */
export function isTwoFactorOtpConfigured(env: NodeJS.Dict<string> = process.env): boolean {
  return isTwoFactorEmailOtpConfigured(env) || isTwoFactorSmsOtpConfigured(env);
}

/**
 * Read a user's delivery facts from `apiome.users`.
 *
 * @param userId The Better Auth user id (`users.id`).
 * @returns The row's channel and phone fields, or `null` when the user does not exist.
 */
export const readOtpDeliveryRow: OtpDeliveryReader = async (userId) => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const pool = require('../db/db');
  const result = await pool.query(
    `SELECT two_factor_otp_channel AS channel, "phoneNumber" AS "phoneNumber",
            "phoneNumberVerified" AS "phoneNumberVerified"
       FROM apiome.users
      WHERE id = $1`,
    [userId],
  );
  return (result.rows[0] as OtpDeliveryRow | undefined) ?? null;
};

/**
 * Decide where a user's code goes, from their stored facts.
 *
 * @param row The user's delivery facts (or `null` when unknown).
 * @param env Environment map; defaults to `process.env`.
 * @returns `sms` only when chosen, verified and deliverable; otherwise `email`.
 */
export function effectiveOtpChannel(
  row: OtpDeliveryRow | null,
  env: NodeJS.Dict<string> = process.env,
): TwoFactorOtpChannel {
  if (
    row?.channel === 'sms' &&
    row.phoneNumberVerified === true &&
    typeof row.phoneNumber === 'string' &&
    row.phoneNumber.length > 0 &&
    isTwoFactorSmsOtpConfigured(env)
  ) {
    return 'sms';
  }
  return 'email';
}

/** Where the next code for a pending sign-in will go, safe to show on the second-step screen. */
export interface OtpDeliveryHint {
  channel: TwoFactorOtpChannel;
  /** For SMS, the masked number (`•••• 0123`); empty for email. */
  destination: string;
  /**
   * Whether that channel can deliver at all. `false` only for an email-channel user on a
   * deployment with SMS but no SendGrid — Better Auth still offers `"otp"` (it is server-level),
   * so the second-step screen hides it instead of promising an email that will not come.
   */
  available: boolean;
}

/**
 * Describe a user's effective delivery for display, without revealing the full number.
 *
 * @param row The user's delivery facts.
 * @param env Environment map; defaults to `process.env`.
 * @returns The channel, a masked destination, and whether it can deliver.
 */
export function describeOtpDelivery(
  row: OtpDeliveryRow | null,
  env: NodeJS.Dict<string> = process.env,
): OtpDeliveryHint {
  const channel = effectiveOtpChannel(row, env);
  if (channel === 'sms') {
    return { channel, destination: maskPhoneNumber(row?.phoneNumber), available: true };
  }
  return { channel, destination: '', available: isTwoFactorEmailOtpConfigured(env) };
}

/**
 * `otpOptions.sendOTP`: deliver a sign-in code by the user's effective channel.
 *
 * @param params.user The user signing in (Better Auth's session user).
 * @param params.otp The 6-digit code (never logged).
 * @param readRow Reads the user's delivery facts (injectable for tests).
 * @param env Environment map; defaults to `process.env`.
 * @throws When the chosen channel cannot deliver; Better Auth logs the failure.
 */
export async function sendTwoFactorOtp(
  params: { user: TwoFactorOtpUser; otp: string },
  readRow: OtpDeliveryReader = readOtpDeliveryRow,
  env: NodeJS.Dict<string> = process.env,
): Promise<void> {
  const row = await readRow(params.user.id);
  if (effectiveOtpChannel(row, env) === 'sms') {
    // Loaded on use: the sender pulls in Better Auth's API module, which the browser-facing
    // importers of this file (Profile, the second-step page) never need.
    const { sendTwoFactorSmsOtp } = await import('./send-two-factor-sms-otp');
    await sendTwoFactorSmsOtp({ phoneNumber: row!.phoneNumber as string, otp: params.otp }, env);
    return;
  }
  await sendTwoFactorEmailOtp({ user: params.user, otp: params.otp }, env);
}

/**
 * Put a user's codes back on email (phoneNumber plugin `callbackOnVerification`).
 *
 * Called whenever a new number is verified: choosing SMS asks for the password (or a fresh
 * sign-in), but adding a number only needs a live session — so a session left open somewhere must
 * not be able to swap in its own phone and start receiving the user's sign-in codes.
 *
 * @param userId The user whose number changed.
 */
export async function resetTwoFactorOtpChannel(userId: string): Promise<void> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const pool = require('../db/db');
  await pool.query(
    `UPDATE apiome.users SET two_factor_otp_channel = 'email'
      WHERE id = $1 AND two_factor_otp_channel <> 'email'`,
    [userId],
  );
}
