/**
 * Narrow the Better Auth `phoneNumber` plugin to "verify a number on my own account" (OLO-9.51 #5071).
 *
 * apiome uses the plugin only to store a verified number for SMS two-factor codes. Out of the box
 * it also signs people in by phone: `/sign-in/phone-number` (password by phone), the password
 * reset pair, and — less obviously — `/phone-number/verify` *without* `updatePhoneNumber`, which
 * finds the user who owns the number and creates a session for them. Any of those would let a
 * phone (or a recycled SIM) stand in for the password and skip two-factor entirely.
 *
 * So:
 * - the sign-in and reset routes are switched off in `auth.ts` (`DISABLED_AUTH_PATHS`), and
 * - this `hooks.before` handler lets `/phone-number/send-otp` and `/phone-number/verify` through
 *   only for a **signed-in** user, only when SMS is configured, only for an E.164 number, and —
 *   for verify — only in `updatePhoneNumber` mode, which attaches the number to the caller's own
 *   account and never creates a session.
 *
 * An unauthenticated `send-otp` is refused too, so the endpoint cannot be used to text arbitrary
 * numbers at apiome's expense.
 *
 * The plugin also makes `phoneNumber` a writable user field, so any other route that creates or
 * updates a user (`/sign-up/email`, …) would store a number nobody verified — enough to claim
 * someone else's number under the unique index. Such a request is refused unless it only clears
 * the number (`/update-user` with `phoneNumber: null`, which the plugin pairs with
 * `phoneNumberVerified: false`).
 */

import { APIError, getAuthoritativeSessionFromCtx } from 'better-auth/api';
import { isE164PhoneNumber } from './phone-number-format';
import { isTwoFactorSmsOtpConfigured } from './sms-otp-config';

/** The phoneNumber plugin routes apiome switches off entirely. */
export const DISABLED_PHONE_NUMBER_PATHS = [
  '/sign-in/phone-number',
  '/phone-number/request-password-reset',
  '/phone-number/reset-password',
] as const;

/** The two plugin routes apiome keeps, each gated by {@link phoneNumberGuardHandler}. */
export const GUARDED_PHONE_NUMBER_PATHS: ReadonlySet<string> = new Set([
  '/phone-number/send-otp',
  '/phone-number/verify',
]);

/** Stable refusal codes, so the Profile page can show the right sentence. */
export const PHONE_NUMBER_GUARD_CODES = {
  notConfigured: 'SMS_NOT_CONFIGURED',
  signInRequired: 'PHONE_NUMBER_SIGN_IN_REQUIRED',
  invalidNumber: 'INVALID_PHONE_NUMBER',
  updateOnly: 'PHONE_NUMBER_UPDATE_ONLY',
  verifyOnly: 'PHONE_NUMBER_VERIFY_ONLY',
} as const;

/** The subset of the Better Auth `hooks.before` context this handler reads. */
interface GuardContext {
  path?: string;
  body?: Record<string, unknown> | null;
}

/**
 * `hooks.before` handler for the phoneNumber plugin's kept routes. A no-op for every other path.
 *
 * @param rawCtx The Better Auth middleware context.
 * @param readSession Reads the request's session; injectable for tests. Defaults to Better Auth's
 *   authoritative (database) read, so a revoked session cannot pass on a cached cookie.
 * @param env Environment map; defaults to `process.env`.
 * @throws APIError `400` when SMS is not configured, the number is not E.164, or verify is not in
 *   `updatePhoneNumber` mode; `401` when there is no session.
 */
export async function phoneNumberGuardHandler(
  rawCtx: unknown,
  readSession: (ctx: unknown) => Promise<{ user?: { id?: string } } | null> = (ctx) =>
    getAuthoritativeSessionFromCtx(ctx as never) as Promise<{ user?: { id?: string } } | null>,
  env: NodeJS.Dict<string> = process.env,
): Promise<void> {
  const ctx = rawCtx as GuardContext;
  if (typeof ctx.path !== 'string') return;
  if (!GUARDED_PHONE_NUMBER_PATHS.has(ctx.path)) {
    const body = ctx.body;
    if (body && typeof body === 'object' && 'phoneNumber' in body && body.phoneNumber !== null) {
      throw new APIError('BAD_REQUEST', {
        message: 'A phone number can only be added by confirming the code sent to it.',
        code: PHONE_NUMBER_GUARD_CODES.verifyOnly,
      });
    }
    return;
  }

  if (!isTwoFactorSmsOtpConfigured(env)) {
    throw new APIError('BAD_REQUEST', {
      message: 'Text-message codes are not available on this server.',
      code: PHONE_NUMBER_GUARD_CODES.notConfigured,
    });
  }

  const body = ctx.body ?? {};
  if (ctx.path === '/phone-number/verify' && body.updatePhoneNumber !== true) {
    throw new APIError('BAD_REQUEST', {
      message: 'A phone number can only be verified for the account you are signed in to.',
      code: PHONE_NUMBER_GUARD_CODES.updateOnly,
    });
  }

  if (!isE164PhoneNumber(body.phoneNumber)) {
    throw new APIError('BAD_REQUEST', {
      message: 'Enter the number with its country code, like +14155550123.',
      code: PHONE_NUMBER_GUARD_CODES.invalidNumber,
    });
  }

  const current = await readSession(rawCtx);
  if (!current?.user?.id) {
    throw new APIError('UNAUTHORIZED', {
      message: 'Sign in to add a phone number.',
      code: PHONE_NUMBER_GUARD_CODES.signInRequired,
    });
  }
}
