/**
 * Where the pending sign-in's one-time code will be sent (OLO-9.51 #5071).
 *
 * The `/login/2fa` screen runs before any session exists, holding only Better Auth's signed
 * `two_factor` cookie — the same proof `/two-factor/send-otp` reads to find the user. This module
 * reads it the same way so the screen can say "We will text a code to •••• 0123" or "We will
 * email a code" before the reader presses **Send**, and can hide the code tab when that user's
 * channel cannot deliver.
 *
 * Advisory only: it decides which words are drawn, never whether a code is accepted. Any failure
 * (no cookie, bad signature, expired challenge, database down) answers `null` and the screen
 * falls back to the email wording it had before.
 */

import { cookies } from 'next/headers';
import { readFirstCookie, unsignBetterAuthCookie } from './better-auth-signed-cookie';
import { resolveBetterAuthSecret } from './better-auth-session';
import { TWO_FACTOR_COOKIE_NAMES } from './two-factor-trust-cookie';
import {
  describeOtpDelivery,
  readOtpDeliveryRow,
  type OtpDeliveryHint,
  type OtpDeliveryReader,
} from './two-factor-otp-dispatch';

/** Looks up the user id a challenge identifier belongs to; `null` when it is gone. */
export type ChallengeUserReader = (identifier: string) => Promise<string | null>;

/**
 * Default {@link ChallengeUserReader}: Better Auth's verification table, through its adapter.
 *
 * @param identifier The unsigned `two_factor` cookie value.
 * @returns The challenged user's id, or `null`.
 */
const readChallengeUser: ChallengeUserReader = async (identifier) => {
  const { auth } = await import('./auth');
  const ctx = await auth.$context;
  const verification = await ctx.internalAdapter.findVerificationValue(identifier);
  if (!verification || new Date(verification.expiresAt).getTime() < Date.now()) return null;
  return typeof verification.value === 'string' ? verification.value : null;
};

/**
 * Describe where the pending challenge's code will go.
 *
 * @param deps Injectable readers (tests).
 * @returns The delivery hint, or `null` when the challenge cannot be read.
 */
export async function getPendingOtpDelivery(
  deps: {
    readCookie?: () => Promise<string | null>;
    readUser?: ChallengeUserReader;
    readRow?: OtpDeliveryReader;
    secret?: string;
  } = {},
): Promise<OtpDeliveryHint | null> {
  try {
    const raw = deps.readCookie
      ? await deps.readCookie()
      : readFirstCookie(await cookies(), TWO_FACTOR_COOKIE_NAMES);
    const secret = deps.secret ?? resolveBetterAuthSecret();
    if (!raw || !secret) return null;
    const identifier = await unsignBetterAuthCookie(raw, secret);
    if (!identifier) return null;
    const userId = await (deps.readUser ?? readChallengeUser)(identifier);
    if (!userId) return null;
    return describeOtpDelivery(await (deps.readRow ?? readOtpDeliveryRow)(userId));
  } catch (error) {
    console.warn(
      '[auth] pending two-factor delivery lookup failed:',
      error instanceof Error ? error.name : 'unknown',
    );
    return null;
  }
}
