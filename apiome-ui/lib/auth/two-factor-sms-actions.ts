'use server';

/**
 * Profile → Security server actions for SMS two-factor (OLO-9.51 #5071).
 *
 * The number itself is added through Better Auth's `phoneNumber` plugin from the browser
 * (`authClient.phoneNumber.sendOtp` / `.verify({ updatePhoneNumber: true })`, gated by
 * `phone-number-guard.ts`). These actions cover what the plugin does not: reading the user's
 * delivery settings, choosing where codes go, and removing the number.
 *
 * Every action is session-bound — it reads and writes the caller's own row and takes no user id.
 *
 * Next.js requires every export from a `'use server'` file to be an async server action.
 */

import { headers } from 'next/headers';
import { isTwoFactorEmailOtpConfigured } from './send-two-factor-email-otp';
import { isTwoFactorSmsOtpConfigured } from './sms-otp-config';
import { maskPhoneNumber } from './phone-number-format';
import { readOtpDeliveryRow, type TwoFactorOtpChannel } from './two-factor-otp-dispatch';

/** What Profile → Security needs to draw the text-message settings. */
export interface SmsTwoFactorStatus {
  /** Whether this server can send texts (Twilio configured). */
  smsAvailable: boolean;
  /** Whether this server can send email codes (SendGrid configured). */
  emailAvailable: boolean;
  /** The verified number, masked (`•••• 0123`), or `null` when there is none. */
  phoneNumber: string | null;
  /** The stored choice — where codes go when the number and the channel are both in place. */
  channel: TwoFactorOtpChannel;
}

/** Why a delivery change was refused, as a stable code the dialog maps to a sentence. */
export type OtpChannelRefusal =
  | 'UNAUTHENTICATED'
  | 'TWO_FACTOR_NOT_ENABLED'
  | 'SMS_NOT_CONFIGURED'
  | 'PHONE_NUMBER_NOT_VERIFIED'
  | 'INVALID_PASSWORD'
  | 'REAUTH_REQUIRED'
  | 'FAILED';

/** The outcome of {@link setTwoFactorOtpChannel} / {@link removePhoneNumber}. */
export type SmsActionResult = { ok: true } | { ok: false; error: OtpChannelRefusal };

/** The signed-in user, reduced to what these actions read. */
interface CurrentUser {
  id: string;
  twoFactorEnabled: boolean;
  sessionCreatedAt: Date | string | number | undefined;
}

/**
 * Read the caller's Better Auth session from the request (authoritative — not the cookie cache).
 *
 * @returns The user, or `null` when signed out.
 */
async function currentUser(): Promise<CurrentUser | null> {
  const { auth } = await import('./auth');
  const current = await auth.api.getSession({
    headers: await headers(),
    query: { disableCookieCache: true },
  });
  const id = current?.user?.id;
  if (!id) return null;
  return {
    id,
    twoFactorEnabled: Boolean((current.user as { twoFactorEnabled?: boolean }).twoFactorEnabled),
    sessionCreatedAt: current.session?.createdAt,
  };
}

/**
 * Read the signed-in user's SMS two-factor settings.
 *
 * @returns The status; `null` when signed out or the row cannot be read.
 */
export async function getSmsTwoFactorStatus(): Promise<SmsTwoFactorStatus | null> {
  try {
    const user = await currentUser();
    if (!user) return null;
    const row = await readOtpDeliveryRow(user.id);
    const verified = row?.phoneNumberVerified === true && Boolean(row.phoneNumber);
    return {
      smsAvailable: isTwoFactorSmsOtpConfigured(),
      emailAvailable: isTwoFactorEmailOtpConfigured(),
      phoneNumber: verified ? maskPhoneNumber(row?.phoneNumber) : null,
      channel: row?.channel === 'sms' ? 'sms' : 'email',
    };
  } catch (error) {
    console.warn(
      '[auth] SMS two-factor status failed:',
      error instanceof Error ? error.name : 'unknown',
    );
    return null;
  }
}

/**
 * Prove it is the account holder before a delivery change: the password when the account has one,
 * otherwise a sign-in within the re-authentication window (the same rule as turning two-factor on
 * or off, `two-factor-reauth.ts`).
 *
 * @param user The signed-in user.
 * @param password What the reader typed (ignored for a passwordless account).
 * @returns `null` when proven, or the refusal.
 */
async function confirmIdentity(
  user: CurrentUser,
  password: string | undefined,
): Promise<OtpChannelRefusal | null> {
  const { auth } = await import('./auth');
  const context = await auth.$context;
  const { hasCredentialPassword } = await import('./two-factor-reauth');
  if (!hasCredentialPassword(await context.internalAdapter.findAccounts(user.id))) {
    const { isSessionFresh } = await import('./two-factor-policy');
    return isSessionFresh(user.sessionCreatedAt) ? null : 'REAUTH_REQUIRED';
  }
  if (!password) return 'INVALID_PASSWORD';
  try {
    await auth.api.verifyPassword({ body: { password }, headers: await headers() });
    return null;
  } catch {
    return 'INVALID_PASSWORD';
  }
}

/**
 * Choose where the signed-in user's two-factor codes go.
 *
 * Choosing SMS needs two-factor on, Twilio configured, and a verified number. Either direction
 * needs the password (or a fresh sign-in for a passwordless account) — where the codes go decides
 * who can finish a sign-in.
 *
 * @param input.channel `email` or `sms`.
 * @param input.password The account password (omit for a passwordless account).
 * @returns `{ ok: true }`, or the refusal code.
 */
export async function setTwoFactorOtpChannel(input: {
  channel: TwoFactorOtpChannel;
  password?: string;
}): Promise<SmsActionResult> {
  try {
    if (input?.channel !== 'email' && input?.channel !== 'sms')
      return { ok: false, error: 'FAILED' };
    const user = await currentUser();
    if (!user) return { ok: false, error: 'UNAUTHENTICATED' };
    if (!user.twoFactorEnabled) return { ok: false, error: 'TWO_FACTOR_NOT_ENABLED' };
    if (input.channel === 'sms') {
      if (!isTwoFactorSmsOtpConfigured()) return { ok: false, error: 'SMS_NOT_CONFIGURED' };
      const row = await readOtpDeliveryRow(user.id);
      if (row?.phoneNumberVerified !== true || !row.phoneNumber) {
        return { ok: false, error: 'PHONE_NUMBER_NOT_VERIFIED' };
      }
    }
    const refusal = await confirmIdentity(user, input.password);
    if (refusal) return { ok: false, error: refusal };

    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pool = require('../db/db');
    // The `sms` write re-checks the number in the same statement, so a number removed between the
    // read above and this write cannot leave the channel on SMS.
    const result = await pool.query(
      `UPDATE apiome.users SET two_factor_otp_channel = $2
        WHERE id = $1
          AND ($2 = 'email' OR ("phoneNumber" IS NOT NULL AND "phoneNumberVerified" = true))`,
      [user.id, input.channel],
    );
    return result.rowCount === 1 ? { ok: true } : { ok: false, error: 'PHONE_NUMBER_NOT_VERIFIED' };
  } catch (error) {
    console.warn('[auth] set OTP channel failed:', error instanceof Error ? error.name : 'unknown');
    return { ok: false, error: 'FAILED' };
  }
}

/**
 * Remove the signed-in user's phone number and put their codes back on email.
 *
 * Needs only the session: removing the number can only move codes to the account's email.
 *
 * @returns `{ ok: true }`, or the refusal code.
 */
export async function removePhoneNumber(): Promise<SmsActionResult> {
  try {
    const user = await currentUser();
    if (!user) return { ok: false, error: 'UNAUTHENTICATED' };
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pool = require('../db/db');
    await pool.query(
      `UPDATE apiome.users
          SET "phoneNumber" = NULL, "phoneNumberVerified" = false, two_factor_otp_channel = 'email'
        WHERE id = $1`,
      [user.id],
    );
    return { ok: true };
  } catch (error) {
    console.warn(
      '[auth] remove phone number failed:',
      error instanceof Error ? error.name : 'unknown',
    );
    return { ok: false, error: 'FAILED' };
  }
}
