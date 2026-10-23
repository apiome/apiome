/**
 * Email (credential) sign-up — the pure parts (SGN-1.1, #5650).
 *
 * A person signs up with a name, an email address and a password. The account is created
 * unverified, and an email carries a one-time link; opening it verifies the account, signs the
 * person in and hands them to the first-tenant onboarding wizard. This module holds everything
 * about that flow that needs no database, network or Next.js runtime, so it is unit-tested
 * directly:
 *
 * - **Availability.** Email sign-up needs a mail sender (SendGrid, `SENDGRID_API_KEY` +
 *   `EMAIL_FROM`) and the public base URL the links point at (`BETTER_AUTH_URL`). Without them it is
 *   off and the form says so — never a form that cannot deliver its link.
 * - **Tokens.** 32 random bytes, base64url in the link; only the SHA-256 is stored
 *   (`apiome.email_verification_token`, V313). 24-hour expiry, single use.
 * - **Messages.** The two emails the flow sends: the verification link, and — when the address
 *   already has an account — a note saying so with a sign-in link, so the form itself never reveals
 *   whether an address is registered.
 *
 * The server actions are in `email-signup-actions.ts`; the database calls in
 * `lib/db/email-verification.ts`.
 */

import crypto from 'crypto';

import { canonicalizeEmail } from './account-resolution';
import { EMAIL_FROM_ENV, SENDGRID_API_KEY_ENV } from './send-two-factor-email-otp';

/** Env var naming the public base URL of this installation (shared with Better Auth). */
export const PUBLIC_BASE_URL_ENV = 'BETTER_AUTH_URL';

/** How long a verification link stays valid. */
export const VERIFICATION_TOKEN_TTL_MS = 24 * 60 * 60 * 1000;

/** Route the verification link opens. */
export const VERIFY_EMAIL_PATH = '/signup/verify';

/** Where the account-exists email sends the reader. */
export const SIGN_IN_PATH = '/login';

/** The sign-up page; the legacy-queue invitation (SGN-1.3) sends the reader here. */
export const SIGNUP_PATH = '/signup';

/** Longest display name accepted (the `users.name` column). */
export const SIGNUP_NAME_MAX_LENGTH = 255;

/** Longest email address accepted (RFC 5321 path limit). */
export const SIGNUP_EMAIL_MAX_LENGTH = 254;

/** Emails (verification or account-exists) one address may receive per window. */
export const SIGNUP_EMAILS_PER_ADDRESS = 3;

/** Sign-up and resend submissions one client IP may make per window. */
export const SIGNUP_REQUESTS_PER_IP = 20;

/** Window for both sign-up budgets. */
export const SIGNUP_BUDGET_WINDOW_MS = 60 * 60 * 1000;

export { EMAIL_SIGNUP_CODES, type EmailSignupCode } from './email-signup-codes';

/** What a verification link turned out to be. */
export type VerificationTokenState = 'valid' | 'expired' | 'used' | 'invalid';

/**
 * The public base URL links are built on, or `null` when it is not configured.
 *
 * The request's own Host header is never used: it is client-controlled, and a link built from it
 * could point a victim's verification email at another site.
 *
 * @param env Environment map; defaults to `process.env`.
 * @returns The base URL without a trailing slash, or `null` when unset or not http(s).
 */
export function publicBaseUrl(env: NodeJS.Dict<string> = process.env): string | null {
  const raw = env[PUBLIC_BASE_URL_ENV]?.trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
  } catch {
    return null;
  }
}

/**
 * Whether email sign-up can run on this installation: a mail sender and a public base URL.
 *
 * @param env Environment map; defaults to `process.env`.
 * @returns `true` when SendGrid is configured and the base URL is valid.
 */
export function isEmailSignupAvailable(env: NodeJS.Dict<string> = process.env): boolean {
  const key = env[SENDGRID_API_KEY_ENV]?.trim();
  const from = env[EMAIL_FROM_ENV]?.trim();
  return Boolean(key && from && publicBaseUrl(env));
}

/**
 * Canonicalize and shape-check an address.
 *
 * @param email Raw form input (or a stored address).
 * @returns The canonical address, or `null` when it cannot be an email address.
 */
export function canonicalSignupEmail(email: unknown): string | null {
  const canonical = canonicalizeEmail(email);
  if (!canonical || canonical.length > SIGNUP_EMAIL_MAX_LENGTH) return null;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(canonical) ? canonical : null;
}

/**
 * Mint a verification token.
 *
 * @returns The token for the link (base64url, 43 characters) and the hash to store.
 */
export function generateVerificationToken(): { token: string; tokenHash: string } {
  const token = crypto.randomBytes(32).toString('base64url');
  return { token, tokenHash: hashVerificationToken(token) };
}

/**
 * The stored form of a token.
 *
 * @param token The token from a link.
 * @returns Lowercase hex SHA-256.
 */
export function hashVerificationToken(token: string): string {
  return crypto.createHash('sha256').update(token, 'utf8').digest('hex');
}

/**
 * Whether a string can be a token this flow minted — checked before any database read so junk
 * never reaches a query.
 *
 * @param token The value from the link's `token` parameter.
 * @returns `true` for a 43-character base64url string.
 */
export function isWellFormedVerificationToken(token: unknown): token is string {
  return typeof token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(token);
}

/**
 * Classify a stored token row at the moment it is redeemed.
 *
 * @param row The row found by hash, or `null` when none matched.
 * @param now Current time; injectable for tests.
 * @returns `invalid` for no row, `used` once redeemed, `expired` past its expiry, else `valid`.
 */
export function classifyVerificationToken(
  row: { expiresAt: Date; usedAt: Date | null } | null,
  now: Date = new Date()
): VerificationTokenState {
  if (!row) return 'invalid';
  if (row.usedAt) return 'used';
  if (row.expiresAt.getTime() <= now.getTime()) return 'expired';
  return 'valid';
}

/**
 * The link a verification email carries.
 *
 * @param baseUrl From {@link publicBaseUrl}.
 * @param token The plain token.
 * @returns An absolute URL to {@link VERIFY_EMAIL_PATH} with the token as `?token=`.
 */
export function verificationLink(baseUrl: string, token: string): string {
  return `${baseUrl}${VERIFY_EMAIL_PATH}?token=${encodeURIComponent(token)}`;
}

/** An email, ready for the mail client. */
export interface SignupEmailMessage {
  subject: string;
  text: string;
  html: string;
}

/**
 * Escape text for an HTML email body.
 *
 * @param value Untrusted text (a display name, a URL).
 * @returns The text with HTML metacharacters escaped.
 */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Wrap paragraphs and one call-to-action button in the Apiome email frame.
 *
 * Email clients ignore stylesheets, so the frame uses inline styles — the only place in the app
 * where that is the rule rather than the exception.
 *
 * @param paragraphs Plain-text paragraphs (escaped here).
 * @param action The button's label and absolute URL.
 * @returns The HTML body.
 */
function frameHtml(paragraphs: readonly string[], action: { label: string; href: string }): string {
  const body = paragraphs
    .map((line) => `<p style="margin:0 0 16px;font-size:15px;line-height:22px;color:#1f2328">${escapeHtml(line)}</p>`)
    .join('');
  const href = escapeHtml(action.href);
  return (
    '<div style="background:#f6f4ef;padding:32px 16px;font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif">' +
    '<div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e4e0d6;border-radius:12px;padding:32px">' +
    '<p style="margin:0 0 24px;font-size:18px;font-weight:600;color:#1f2328">Apiome</p>' +
    body +
    `<p style="margin:24px 0"><a href="${href}" style="display:inline-block;background:#1b2a5c;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:12px 20px;border-radius:8px">${escapeHtml(action.label)}</a></p>` +
    `<p style="margin:0;font-size:13px;line-height:20px;color:#59636e">If the button does not work, copy this address into your browser:<br><span style="word-break:break-all">${href}</span></p>` +
    '</div></div>'
  );
}

/**
 * The verification email.
 *
 * @param params.name The display name entered on the form (may be blank).
 * @param params.link From {@link verificationLink}.
 * @returns Subject, plain text and HTML.
 */
export function buildVerificationEmail(params: { name?: string | null; link: string }): SignupEmailMessage {
  const name = params.name?.trim();
  const greeting = name ? `Hello ${name},` : 'Hello,';
  const lines = [
    greeting,
    'Confirm your email address to finish creating your Apiome account.',
    'The link works once and expires in 24 hours. If it expires, open the sign-in page and ask for a new one.',
    'If you did not sign up for Apiome, you can ignore this email; no account is created until the address is confirmed.',
  ];
  return {
    subject: 'Confirm your email for Apiome',
    text: [...lines, `Confirm your email: ${params.link}`].join('\n\n'),
    html: frameHtml(lines, { label: 'Confirm email', href: params.link }),
  };
}

/**
 * The email sent when someone signs up with an address that already has an account.
 *
 * The form shows the same "check your email" screen either way, so this message is the only place
 * the owner of the address learns that an account exists — and only the owner can read it.
 *
 * @param params.name The account's display name (may be blank).
 * @param params.signInUrl Absolute URL of the sign-in page.
 * @returns Subject, plain text and HTML.
 */
export function buildAccountExistsEmail(params: {
  name?: string | null;
  signInUrl: string;
}): SignupEmailMessage {
  const name = params.name?.trim();
  const greeting = name ? `Hello ${name},` : 'Hello,';
  const lines = [
    greeting,
    'Someone tried to create an Apiome account with this email address, but you already have one.',
    'Sign in with your password or with the provider you used before. If you have forgotten your password, ask your workspace administrator to reset it.',
    'If this was not you, you can ignore this email; nothing about your account has changed.',
  ];
  return {
    subject: 'You already have an Apiome account',
    text: [...lines, `Sign in: ${params.signInUrl}`].join('\n\n'),
    html: frameHtml(lines, { label: 'Sign in', href: params.signInUrl }),
  };
}

/**
 * The invitation sent once to each person left in the retired sign-up request queue (SGN-1.3,
 * #5652).
 *
 * They asked for an account under the old approval flow; the queue is gone, so this tells them to
 * create the account themselves. The password they typed into the old form is never used: it was
 * never confirmed, so they choose a new one on the sign-up page.
 *
 * @param params.name The name they gave on the old request form (may be blank).
 * @param params.signupUrl Absolute URL of the sign-up page ({@link SIGNUP_PATH}).
 * @returns Subject, plain text and HTML.
 */
export function buildLegacySignupInvitationEmail(params: {
  name?: string | null;
  signupUrl: string;
}): SignupEmailMessage {
  const name = params.name?.trim();
  const greeting = name ? `Hello ${name},` : 'Hello,';
  const lines = [
    greeting,
    'You asked for an Apiome account. Accounts no longer wait for approval, so you can finish creating yours now.',
    'Open the sign-up page, enter this email address and choose a password. We then send you a link to confirm the address.',
    'If you no longer want an account, you can ignore this email; nothing is created until you sign up.',
  ];
  return {
    subject: 'Finish creating your Apiome account',
    text: [...lines, `Create your account: ${params.signupUrl}`].join('\n\n'),
    html: frameHtml(lines, { label: 'Create your account', href: params.signupUrl }),
  };
}
