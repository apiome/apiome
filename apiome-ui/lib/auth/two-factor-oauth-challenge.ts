/**
 * The second factor after an OAuth sign-in (TFA-1.1, #5655).
 *
 * Better Auth's `twoFactor` plugin withholds the session until a code is verified — but only for
 * `/sign-in/email`, `/sign-in/username` and `/sign-in/phone-number`. A provider sign-in ends in
 * `/oauth2/callback/:providerId`, which the plugin does not watch, so an account with two-factor
 * on was let straight in whenever it signed in with GitHub, GitLab, Microsoft or Google. This
 * `hooks.after` handler closes that path by doing for the OAuth callback exactly what the plugin
 * does for a password sign-in:
 *
 * 1. If this browser holds a valid **trusted-device** record for the user, rotate it and let the
 *    session stand — the same skip a password sign-in gets.
 * 2. Otherwise take back the session the callback just issued, start a second-factor **challenge**
 *    (the signed `two_factor` cookie plus its server-side records), and redirect to `/login/2fa`
 *    with the destination the sign-in was heading for.
 *
 * Because the challenge is the plugin's own shape, everything downstream is the plugin's:
 * `verify-totp` / `verify-otp` / `verify-backup-code` find it, issue the session, honour
 * "Trust this device" and count failures toward the lockout (OLO-9.14, #5006).
 *
 * ### Coupling to Better Auth internals — re-check on every upgrade
 *
 * Steps 1 and 2 mirror `better-auth/dist/plugins/two-factor/index.mjs` (its `hooks.after`) and are
 * read back by `verify-two-factor.mjs`. The contract this module depends on, as of 1.6.25:
 *
 * - cookie names `two_factor` and `trust_device` (`constant.mjs`), signed with the auth secret;
 * - a verification record `2fa-<random>` whose value is the user id, and a sibling
 *   `2fa-attempts-<identifier>` whose value is the attempt count, both expiring with the cookie;
 * - a trust cookie of the form `<hmac>!<identifier>`, where the HMAC is SHA-256 over
 *   `<userId>!<identifier>` in unpadded base64url, and a verification record `<identifier>` whose
 *   value is the user id.
 *
 * `tests/two-factor-oauth-challenge.test.ts` pins each of these against the installed package, so a
 * Better Auth upgrade that changes one fails a test rather than silently dropping the challenge.
 * If a future release challenges OAuth sign-ins itself (its matcher gains the callback path), this
 * module must be removed, not kept beside it — the pinning test for the matcher says when.
 */

import { createHmac, timingSafeEqual } from 'node:crypto';
import { deleteSessionCookie, expireCookie } from 'better-auth/cookies';
import { generateRandomString } from 'better-auth/crypto';
import { oauthProviderFromCallbackPath } from './better-auth-account-resolution';
import { isTwoFactorEmailOtpConfigured } from './send-two-factor-email-otp';
import { TRUST_DEVICE_MAX_AGE_SECONDS } from './two-factor-policy';

/** The plugin's challenge cookie (`constant.mjs` `TWO_FACTOR_COOKIE_NAME`). */
export const TWO_FACTOR_COOKIE_NAME = 'two_factor';

/** The plugin's trusted-device cookie (`constant.mjs` `TRUST_DEVICE_COOKIE_NAME`). */
export const TRUST_DEVICE_COOKIE_NAME = 'trust_device';

/** How long a challenge lasts, in seconds — the plugin's `twoFactorCookieMaxAge` default. */
export const TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS = 600;

/** The model the plugin's `twoFactor` rows live under (mapped to `two_factor` by `auth.ts`). */
const TWO_FACTOR_MODEL = 'twoFactor';

/** Where the second step lives. */
const TWO_FACTOR_PAGE = '/login/2fa';

/** A Better Auth cookie definition, as `createAuthCookie` returns it. */
interface AuthCookie {
  name: string;
  attributes: Record<string, unknown>;
}

/** A Better Auth verification record. */
interface VerificationRecord {
  value: string;
  expiresAt: Date;
}

/**
 * The subset of the Better Auth `hooks.after` context this handler reads (structural, so the
 * module does not import Better Auth's internal types).
 */
export interface OAuthChallengeContext {
  /** The request path, e.g. `/oauth2/callback/github`. */
  path?: string;
  context: {
    /** The auth secret cookies and the trust HMAC are signed with. */
    secret: string;
    /** The session the callback just issued, or `null` when it issued none. */
    newSession: {
      user: { id: string; twoFactorEnabled?: boolean | null };
      session: { token: string };
    } | null;
    setNewSession: (session: null) => void;
    /** What the endpoint answered — for the callback, the redirect it threw. */
    returned?: unknown;
    /** Headers accumulated for the response, including the redirect's `Location`. */
    responseHeaders?: Headers;
    createAuthCookie: (name: string, attributes?: { maxAge?: number }) => AuthCookie;
    internalAdapter: {
      deleteSession: (token: string) => Promise<unknown>;
      createVerificationValue: (data: {
        value: string;
        identifier: string;
        expiresAt: Date;
      }) => Promise<unknown>;
      findVerificationValue: (identifier: string) => Promise<VerificationRecord | null | undefined>;
      deleteVerificationByIdentifier: (identifier: string) => Promise<unknown>;
    };
    adapter: {
      findOne: (query: {
        model: string;
        where: { field: string; value: string }[];
      }) => Promise<{ verified?: boolean | null } | null | undefined>;
    };
  };
  getSignedCookie: (name: string, secret: string) => Promise<string | null | undefined | false>;
  setSignedCookie: (
    name: string,
    value: string,
    secret: string,
    attributes?: Record<string, unknown>
  ) => Promise<unknown>;
  /** Builds the redirect the handler throws to replace the callback's own. */
  redirect: (url: string) => unknown;
}

/**
 * The HMAC that binds a trusted-device record to a user — the plugin's
 * `createHMAC('SHA-256', 'base64urlnopad').sign(secret, `${userId}!${identifier}`)`.
 *
 * @param secret The auth secret.
 * @param userId The user the device is trusted for.
 * @param identifier The trust record's identifier.
 * @returns The signature in unpadded base64url.
 */
export function signTrustedDevice(secret: string, userId: string, identifier: string): string {
  return createHmac('sha256', secret).update(`${userId}!${identifier}`).digest('base64url');
}

/**
 * Compare two signatures without leaking where they differ.
 *
 * @param a One signature.
 * @param b The other.
 * @returns `true` when they are byte-for-byte equal.
 */
function sameSignature(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

/**
 * Honour a trusted-device cookie, rotating it as the plugin does on every sign-in.
 *
 * @param ctx The hook context.
 * @param userId The user who just signed in.
 * @returns `true` when this browser is trusted for the user and the second step may be skipped.
 *   A cookie that is forged, expired, or for someone else is expired and yields `false`.
 */
async function consumeTrustedDevice(ctx: OAuthChallengeContext, userId: string): Promise<boolean> {
  const cookie = ctx.context.createAuthCookie(TRUST_DEVICE_COOKIE_NAME, {
    maxAge: TRUST_DEVICE_MAX_AGE_SECONDS,
  });
  const value = await ctx.getSignedCookie(cookie.name, ctx.context.secret);
  if (!value) return false;

  const [token, identifier] = value.split('!');
  if (token && identifier && sameSignature(token, signTrustedDevice(ctx.context.secret, userId, identifier))) {
    const record = await ctx.context.internalAdapter.findVerificationValue(identifier);
    if (record && record.value === userId && new Date(record.expiresAt).getTime() > Date.now()) {
      await ctx.context.internalAdapter.deleteVerificationByIdentifier(identifier);
      const nextIdentifier = `trust-device-${generateRandomString(32)}`;
      await ctx.context.internalAdapter.createVerificationValue({
        value: userId,
        identifier: nextIdentifier,
        expiresAt: new Date(Date.now() + TRUST_DEVICE_MAX_AGE_SECONDS * 1000),
      });
      await ctx.setSignedCookie(
        cookie.name,
        `${signTrustedDevice(ctx.context.secret, userId, nextIdentifier)}!${nextIdentifier}`,
        ctx.context.secret,
        cookie.attributes
      );
      return true;
    }
  }
  // `expireCookie` is typed against Better Auth's own context; ours is the structural subset.
  expireCookie(ctx as never, cookie as never);
  return false;
}

/**
 * Where the OAuth callback was about to send the browser.
 *
 * The callback answers by throwing a redirect, so its destination is the `Location` on the
 * returned error or on the accumulated response headers.
 *
 * @param ctx The hook context.
 * @returns The destination, or `null` when the callback did not redirect.
 */
function callbackDestination(ctx: OAuthChallengeContext): string | null {
  const returned = ctx.context.returned as { headers?: Headers } | undefined;
  return (
    returned?.headers?.get?.('location') ?? ctx.context.responseHeaders?.get('location') ?? null
  );
}

/**
 * Which second factors the user can be offered — the plugin's `twoFactorMethods`.
 *
 * @param ctx The hook context.
 * @param userId The user being challenged.
 * @returns `totp` when the user has a verified authenticator, `otp` when the server can mail a code.
 */
async function availableMethods(ctx: OAuthChallengeContext, userId: string): Promise<string[]> {
  const methods: string[] = [];
  const enrolment = await ctx.context.adapter.findOne({
    model: TWO_FACTOR_MODEL,
    where: [{ field: 'userId', value: userId }],
  });
  if (enrolment && enrolment.verified !== false) methods.push('totp');
  if (isTwoFactorEmailOtpConfigured()) methods.push('otp');
  return methods;
}

/**
 * `hooks.after` handler: challenge an OAuth sign-in for the second factor.
 *
 * A no-op for every request that is not an OAuth callback, for a callback that issued no session
 * (an error redirect, or Better Auth's own account-link branch), and for a user without
 * two-factor. For an enrolled user it either honours a trusted device or replaces the callback's
 * redirect with one to `/login/2fa` — in which case it **throws** that redirect, as Better Auth
 * hooks do.
 *
 * @param rawCtx The Better Auth middleware context.
 * @throws The redirect to the second step, when a challenge was started.
 */
export async function oauthTwoFactorChallengeHandler(rawCtx: unknown): Promise<void> {
  const ctx = rawCtx as OAuthChallengeContext;
  if (!oauthProviderFromCallbackPath(ctx.path)) return;

  const issued = ctx.context.newSession;
  if (!issued?.user?.twoFactorEnabled) return;
  const userId = issued.user.id;

  if (await consumeTrustedDevice(ctx, userId)) return;

  // The callback has already created the session and set its cookie. Until the second factor is
  // verified there must be neither, and hooks that run later must not see a session that is gone.
  deleteSessionCookie(ctx as never, true);
  await ctx.context.internalAdapter.deleteSession(issued.session.token);
  ctx.context.setNewSession(null);

  const cookie = ctx.context.createAuthCookie(TWO_FACTOR_COOKIE_NAME, {
    maxAge: TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS,
  });
  const identifier = `2fa-${generateRandomString(20)}`;
  const expiresAt = new Date(Date.now() + TWO_FACTOR_CHALLENGE_MAX_AGE_SECONDS * 1000);
  await ctx.context.internalAdapter.createVerificationValue({ value: userId, identifier, expiresAt });
  await ctx.context.internalAdapter.createVerificationValue({
    value: '0',
    identifier: `2fa-attempts-${identifier}`,
    expiresAt,
  });
  await ctx.setSignedCookie(cookie.name, identifier, ctx.context.secret, cookie.attributes);

  const query = new URLSearchParams();
  const destination = callbackDestination(ctx);
  // The page re-validates this against the callback allowlist; it is only carried here.
  if (destination) query.set('callbackUrl', destination);
  const methods = await availableMethods(ctx, userId);
  if (methods.length > 0) query.set('methods', methods.join(','));

  throw ctx.redirect(`${TWO_FACTOR_PAGE}?${query.toString()}`);
}
