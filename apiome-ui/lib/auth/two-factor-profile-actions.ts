'use server';

/**
 * Profile self-service helpers for 2FA management (OLO-9.15 #5015).
 *
 * Better Auth exposes `viewBackupCodes` as a server-only API (no client method) and stores
 * trusted-device skip as a signed `trust_device` cookie — not a listable multi-device table.
 * These actions bridge that into the Profile Security UI: remaining backup-code count,
 * whether *this browser* is trusted, and revoke-this-device (expire cookie + drop verification).
 *
 * Next.js requires every export from a `'use server'` file to be an async server action.
 */

import { cookies, headers } from 'next/headers';
import { constantTimeEqual, makeSignature } from 'better-auth/crypto';
import { getSharedCookieDomain } from './cookie-options';
import { resolveBetterAuthSecret } from './better-auth-session';
import {
  TRUST_DEVICE_COOKIE_NAMES,
} from './two-factor-trust-cookie';
import { isTwoFactorEmailOtpConfigured } from './send-two-factor-email-otp';

/**
 * Read the Better Auth trust-device cookie value from the request cookie jar, if present.
 *
 * @param store Next.js cookie store.
 * @returns Raw cookie value, or `null` when neither name is set.
 */
function readTrustDeviceCookieValue(store: {
  get: (name: string) => { value: string } | undefined;
}): string | null {
  for (const name of TRUST_DEVICE_COOKIE_NAMES) {
    const value = store.get(name)?.value;
    if (value) return value;
  }
  return null;
}

/**
 * Verify a Better Auth signed cookie and return the unsigned payload (`token!trustIdentifier`).
 *
 * Mirrors `better-call`'s `getSignedCookie` signature check so we can extract the trust identifier
 * without an endpoint context.
 *
 * @param raw Cookie value from the jar (URI-decoded).
 * @param secret Better Auth signing secret.
 * @returns Unsigned payload, or `null` when missing/invalid.
 */
async function unsignTrustDeviceCookie(
  raw: string,
  secret: string
): Promise<string | null> {
  const signatureStartPos = raw.lastIndexOf('.');
  if (signatureStartPos < 1) return null;
  const signedValue = raw.substring(0, signatureStartPos);
  const signature = raw.substring(signatureStartPos + 1);
  if (signature.length !== 44 || !signature.endsWith('=')) return null;
  const expected = await makeSignature(signedValue, secret);
  return constantTimeEqual(signature, expected) ? signedValue : null;
}

/**
 * Expire both trust-device cookie name variants (host-only and shared-domain when configured).
 *
 * @param store Next.js mutable cookie store.
 */
function expireTrustDeviceCookies(store: {
  set: (name: string, value: string, options: Record<string, unknown>) => void;
}): void {
  const domain = getSharedCookieDomain();
  for (const name of TRUST_DEVICE_COOKIE_NAMES) {
    const secure = name.startsWith('__') || process.env.NODE_ENV === 'production';
    const base = {
      path: '/',
      httpOnly: true,
      sameSite: 'lax' as const,
      secure,
      maxAge: 0,
    };
    store.set(name, '', base);
    if (domain) {
      store.set(name, '', { ...base, domain });
    }
  }
}

/**
 * Return how many unused backup codes remain for the signed-in user.
 *
 * Calls Better Auth's server-only `viewBackupCodes` with the session user id. Used codes are
 * removed from the stored set, so `backupCodes.length` is the remaining count.
 *
 * @returns `{ remaining }` — `null` when unauthenticated, 2FA is off, or the lookup fails.
 */
export async function getBackupCodeStatus(): Promise<{ remaining: number | null }> {
  const { getAuthSession } = await import('./server-session');
  const session = await getAuthSession();
  if (!session?.user?.user_id || !session.user.twoFactorEnabled) {
    return { remaining: null };
  }

  try {
    const { auth } = await import('./auth');
    const result = (await auth.api.viewBackupCodes({
      body: { userId: session.user.user_id },
      headers: await headers(),
    })) as { backupCodes?: string[] } | null;

    if (!Array.isArray(result?.backupCodes)) {
      return { remaining: null };
    }
    return { remaining: result.backupCodes.length };
  } catch (error) {
    console.warn(
      '[auth] viewBackupCodes failed:',
      error instanceof Error ? error.name : 'unknown'
    );
    return { remaining: null };
  }
}

/**
 * Whether the current browser holds a Better Auth trust-device cookie.
 *
 * Presence is enough for the profile UI; full HMAC validation happens on the next credential
 * sign-in (and on revoke).
 *
 * @returns `{ trusted: true }` when a trust-device cookie is present.
 */
export async function getTrustedDeviceStatus(): Promise<{ trusted: boolean }> {
  const store = await cookies();
  return { trusted: Boolean(readTrustDeviceCookieValue(store)) };
}

/**
 * Forget this browser as a trusted device: delete the verification row (when the signed cookie
 * can be parsed) and expire the trust-device cookie variants.
 *
 * Does not affect other browsers — Better Auth has no multi-device trust list.
 *
 * @returns `{ ok: true }` when the session is valid and cookies were cleared (even if no cookie
 *   was present); `{ ok: false }` when unauthenticated.
 */
export async function revokeThisTrustedDevice(): Promise<{ ok: boolean }> {
  const { getAuthSession } = await import('./server-session');
  const session = await getAuthSession();
  if (!session?.user?.user_id) {
    return { ok: false };
  }

  const store = await cookies();
  const raw = readTrustDeviceCookieValue(store);
  const secret = resolveBetterAuthSecret();

  if (raw && secret) {
    try {
      const unsigned = await unsignTrustDeviceCookie(raw, secret);
      const trustId = unsigned?.split('!')[1];
      if (trustId) {
        const { auth } = await import('./auth');
        const ctx = await auth.$context;
        await ctx.internalAdapter.deleteVerificationByIdentifier(trustId);
      }
    } catch (error) {
      // Cookie expiry still proceeds — orphaned verification rows expire on their own TTL.
      console.warn(
        '[auth] trust-device verification cleanup failed:',
        error instanceof Error ? error.name : 'unknown'
      );
    }
  }

  expireTrustDeviceCookies(store);
  return { ok: true };
}

/**
 * Whether email OTP is available as a login second factor (OLO-9.50 #5070).
 *
 * Better Auth registers `otpOptions.sendOTP` only when SendGrid is configured; the Profile
 * Security UI uses this so TOTP-only deployments do not advertise email OTP.
 *
 * @returns `{ available: true }` when `SENDGRID_API_KEY` and `EMAIL_FROM` are set.
 */
export async function getEmailOtpAvailability(): Promise<{ available: boolean }> {
  return { available: isTwoFactorEmailOtpConfigured() };
}

/** A provider the reader can sign in with again to confirm it is them. */
export interface ReauthProvider {
  /** The provider id `signIn()` takes, e.g. `github`. */
  id: string;
  /** The provider's display name, e.g. `GitHub`. */
  label: string;
}

/** How this account proves itself before a two-factor change (TFA-1.1 #5655). */
export interface TwoFactorReauthStatus {
  /** Whether the account has a password; if so the dialogs ask for it, as before. */
  hasPassword: boolean;
  /**
   * For an account without a password: whether its session is recent enough to stand in for one
   * (`isSessionFresh`). Always `false` when the session cannot be read.
   */
  fresh: boolean;
  /** The linked, enabled providers the reader can sign in with again. */
  providers: ReauthProvider[];
}

/**
 * Report how the signed-in account can confirm it is them before changing two-factor settings.
 *
 * The answer mirrors what `twoFactorReauthHandler` enforces — it reads the same Better Auth
 * accounts and the same session timestamp — so the Profile page can draw the right first step
 * instead of discovering the refusal after a click. It is advisory: the server decides.
 *
 * Fails toward the existing behaviour: when anything cannot be read the account is reported as
 * having a password, so the dialogs keep asking for one and the server gives the real answer.
 *
 * @returns The account's re-authentication status.
 */
export async function getTwoFactorReauthStatus(): Promise<TwoFactorReauthStatus> {
  const unknown: TwoFactorReauthStatus = { hasPassword: true, fresh: false, providers: [] };
  try {
    const { auth } = await import('./auth');
    const current = await auth.api.getSession({ headers: await headers() });
    const userId = current?.user?.id;
    if (!userId) return unknown;

    const context = await auth.$context;
    const accounts = (await context.internalAdapter.findAccounts(userId)) ?? [];
    const { hasCredentialPassword } = await import('./two-factor-reauth');
    if (hasCredentialPassword(accounts)) return unknown;

    const { isSessionFresh } = await import('./two-factor-policy');
    const { providerSummaries } = await import('./provider-registry');
    const { resolveProviderEnv } = await import('./provider-config-resolver');
    const linked = new Set(accounts.map((account) => account.providerId));
    const providers = providerSummaries(await resolveProviderEnv())
      .filter((provider) => provider.enabled && linked.has(provider.id))
      .map((provider) => ({ id: provider.id, label: provider.label }));

    return {
      hasPassword: false,
      fresh: isSessionFresh(current.session?.createdAt),
      providers,
    };
  } catch (error) {
    console.warn(
      '[auth] two-factor re-auth status failed:',
      error instanceof Error ? error.name : 'unknown'
    );
    return unknown;
  }
}

/** Whether the signed-in user's two-factor was reset by an administrator and not yet set up again. */
export interface TwoFactorResetNoticeStatus {
  /** When the reset happened (ISO 8601), or `null` when there is nothing to tell the user. */
  resetAt: string | null;
}

/**
 * Read the signed-in user's own id, or `null` when there is no session.
 *
 * @returns The session user's id.
 */
async function currentUserId(): Promise<string | null> {
  const { getAuthSession } = await import('./server-session');
  const session = await getAuthSession();
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  return typeof userId === 'string' && userId ? userId : null;
}

/**
 * Whether to tell the signed-in user that an administrator reset their two-factor (TFA-1.2 #5656).
 *
 * apiome-rest stamps `users.two_factor_reset_at` when it resets a user's two-factor. The stamp
 * stands until the user sets two-factor up again or dismisses the notice. Session-bound: it reads
 * the caller's own row and takes no argument, so it cannot be asked about anyone else.
 *
 * @returns `{ resetAt }` — `null` when unauthenticated, when there is no outstanding reset, when
 *   the user has since enrolled again, or when the row cannot be read (the notice is advisory).
 */
export async function getTwoFactorResetNotice(): Promise<TwoFactorResetNoticeStatus> {
  try {
    const userId = await currentUserId();
    if (!userId) return { resetAt: null };
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pool = require('../db/db');
    const result = await pool.query(
      `SELECT two_factor_reset_at
         FROM apiome.users
        WHERE id = $1 AND deleted_at IS NULL AND COALESCE("twoFactorEnabled", false) = false`,
      [userId]
    );
    const stamp = result.rows[0]?.two_factor_reset_at;
    return { resetAt: stamp ? new Date(stamp).toISOString() : null };
  } catch (error) {
    console.warn(
      '[auth] two-factor reset notice read failed:',
      error instanceof Error ? error.name : 'unknown'
    );
    return { resetAt: null };
  }
}

/**
 * Clear the signed-in user's "two-factor was reset" notice (TFA-1.2 #5656).
 *
 * Called when the user dismisses the notice and when they finish setting two-factor up again.
 * Session-bound, like {@link getTwoFactorResetNotice}: it clears the caller's own stamp only.
 *
 * @returns `{ ok: true }` once cleared (or when there was nothing to clear); `{ ok: false }` when
 *   unauthenticated or the write failed.
 */
export async function dismissTwoFactorResetNotice(): Promise<{ ok: boolean }> {
  try {
    const userId = await currentUserId();
    if (!userId) return { ok: false };
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pool = require('../db/db');
    await pool.query(
      `UPDATE apiome.users SET two_factor_reset_at = NULL
        WHERE id = $1 AND two_factor_reset_at IS NOT NULL`,
      [userId]
    );
    return { ok: true };
  } catch (error) {
    console.warn(
      '[auth] two-factor reset notice dismiss failed:',
      error instanceof Error ? error.name : 'unknown'
    );
    return { ok: false };
  }
}
