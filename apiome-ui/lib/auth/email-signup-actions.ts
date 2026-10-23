'use server';

/**
 * Email (credential) sign-up server actions (SGN-1.1, #5650).
 *
 * Three actions, each safe to call from the browser with untrusted input:
 *
 * - {@link startEmailSignup} — the sign-up form. Creates an unverified account and emails a
 *   one-time link. An address that already has an account gets an email saying so instead; the
 *   form answers the same way in both cases, so it never reveals whether an address is registered.
 * - {@link resendSignupVerification} — "Resend email", from the check-your-email screen and from an
 *   expired or used link. Answers the same way whether or not anything was sent.
 * - {@link verifyEmailSignup} — the link. Marks the account verified and returns a one-time code
 *   the page exchanges for a session (`signIn('credentials', { payload: { oneTimeCode } })`, the
 *   path OAuth sign-up already uses). With no workspace yet, the person then meets the first-tenant
 *   onboarding wizard (`FirstTenantOnboardingGuard`).
 *
 * Safeguards: the SGN-1.4 sign-up policy is checked before the address is looked up, so a refusal
 * never depends on whether an account exists; per-IP and per-address budgets bound the email a
 * stranger can trigger; links carry 256 random bits, are stored hashed, expire after 24 hours and
 * work once. Neither sign-in engine admits an unverified account (`users.verified`), so a created
 * but unconfirmed account cannot be used.
 */

import { headers } from 'next/headers';

import { createUser } from '../db/admin-helper';
import {
  findSignupAccount,
  issueVerificationToken,
  redeemVerificationToken,
  type SignupAccount,
} from '../db/email-verification';
import { insertAuthOneTimeCode } from '../db/oauth-signup';
import { resolveEmailSignupDecision } from './account-resolution';
import { resolveClientIp } from './client-ip';
import {
  EMAIL_SIGNUP_CODES,
  SIGN_IN_PATH,
  SIGNUP_BUDGET_WINDOW_MS,
  SIGNUP_EMAILS_PER_ADDRESS,
  SIGNUP_NAME_MAX_LENGTH,
  SIGNUP_REQUESTS_PER_IP,
  VERIFICATION_TOKEN_TTL_MS,
  buildAccountExistsEmail,
  buildVerificationEmail,
  canonicalSignupEmail,
  generateVerificationToken,
  hashVerificationToken,
  isEmailSignupAvailable,
  isWellFormedVerificationToken,
  publicBaseUrl,
  verificationLink,
  type VerificationTokenState,
} from './email-signup';
import { checkRequestBudget } from './login-rate-limit';
import { validatePassword } from './password-policy';
import { sendSignupEmail } from './send-signup-email';
import { resolveSignupPolicy } from './signup-policy-resolver';

/** What the sign-up form and the resend button are told. */
export type EmailSignupResult =
  | { ok: true }
  | {
      ok: false;
      /** An `EMAIL_SIGNUP_CODES` value or an SGN-1.4 policy code (`signup-…`). */
      code: string;
      /** For `email-signup-invalid`: which field and why, as a sentence. */
      message?: string;
    };

/** What the verification page is told. */
export type VerifyEmailSignupResult =
  | { state: 'valid'; oneTimeCode: string }
  | { state: Exclude<VerificationTokenState, 'valid'> };

/**
 * Charge the caller's IP against the sign-up budget.
 *
 * @returns `true` while the client is within budget.
 */
async function withinIpBudget(): Promise<boolean> {
  const ip = resolveClientIp(await headers());
  return checkRequestBudget(`signup-ip:${ip}`, SIGNUP_REQUESTS_PER_IP, SIGNUP_BUDGET_WINDOW_MS).allowed;
}

/**
 * Charge an address against the per-address email budget.
 *
 * @param canonicalEmail The address.
 * @returns `true` while the address may receive another email.
 */
function withinAddressBudget(canonicalEmail: string): boolean {
  return checkRequestBudget(
    `signup-addr:${canonicalEmail}`,
    SIGNUP_EMAILS_PER_ADDRESS,
    SIGNUP_BUDGET_WINDOW_MS
  ).allowed;
}

/**
 * Issue a fresh link for an unverified account and email it.
 *
 * @param account The account (its stored email and name are used).
 * @param baseUrl From `publicBaseUrl`.
 * @returns `true` once the email was accepted for delivery.
 */
async function sendVerification(account: SignupAccount, baseUrl: string): Promise<boolean> {
  const { token, tokenHash } = generateVerificationToken();
  await issueVerificationToken(account.id, tokenHash, new Date(Date.now() + VERIFICATION_TOKEN_TTL_MS));
  return sendSignupEmail(
    account.email,
    buildVerificationEmail({ name: account.name, link: verificationLink(baseUrl, token) })
  );
}

/**
 * Tell the owner of an address that it already has an account.
 *
 * @param account The existing account.
 * @param baseUrl From `publicBaseUrl`.
 * @returns `true` once the email was accepted for delivery.
 */
async function sendAccountExists(account: SignupAccount, baseUrl: string): Promise<boolean> {
  return sendSignupEmail(
    account.email,
    buildAccountExistsEmail({ name: account.name, signInUrl: `${baseUrl}${SIGN_IN_PATH}` })
  );
}

/**
 * Sign up with a name, an email address and a password.
 *
 * Order matters for privacy: input and policy are checked first, the address is looked up last,
 * and every branch after the lookup answers `{ ok: true }` (or the same send failure), so the
 * response is identical for a new and a registered address.
 *
 * @param input.name Display name.
 * @param input.email Address (canonicalized here: trimmed and lowercased).
 * @param input.password Password, checked against the credential policy.
 * @returns `{ ok: true }` when the person should check their email; otherwise a code.
 */
export async function startEmailSignup(input: {
  name: unknown;
  email: unknown;
  password: unknown;
}): Promise<EmailSignupResult> {
  const baseUrl = publicBaseUrl();
  if (!isEmailSignupAvailable() || !baseUrl) {
    return { ok: false, code: EMAIL_SIGNUP_CODES.UNAVAILABLE };
  }
  if (!(await withinIpBudget())) return { ok: false, code: EMAIL_SIGNUP_CODES.RATE_LIMITED };

  const name = typeof input?.name === 'string' ? input.name.trim() : '';
  if (!name || name.length > SIGNUP_NAME_MAX_LENGTH) {
    return { ok: false, code: EMAIL_SIGNUP_CODES.INVALID, message: 'Enter your name.' };
  }
  const email = canonicalSignupEmail(input?.email);
  if (!email) {
    return { ok: false, code: EMAIL_SIGNUP_CODES.INVALID, message: 'Enter a valid email address.' };
  }
  const passwordError = validatePassword(input?.password);
  if (passwordError) return { ok: false, code: EMAIL_SIGNUP_CODES.INVALID, message: `${passwordError}.` };

  // The policy decision for a *new* address — computed before the lookup, so a refusal (closed,
  // invite-only, domain not allowed) is the same whether or not the address has an account.
  const decision = resolveEmailSignupDecision(email, await resolveSignupPolicy(), null);
  if (decision.action === 'reject') return { ok: false, code: decision.code };

  if (!withinAddressBudget(email)) return { ok: false, code: EMAIL_SIGNUP_CODES.RATE_LIMITED };

  try {
    let account = await findSignupAccount(email);
    if (!account) {
      const created = JSON.parse(await createUser(name, email, input.password as string, false));
      // A concurrent sign-up for the same address may have won the unique index; read it back.
      account = await findSignupAccount(email);
      if (!created.success && !account) throw new Error('user insert failed');
      if (created.success && account) {
        const sent = await sendVerification(account, baseUrl);
        return sent ? { ok: true } : { ok: false, code: EMAIL_SIGNUP_CODES.SEND_FAILED };
      }
    }
    if (!account) throw new Error('account lookup failed');
    // An existing address: a disabled account gets nothing, an unconfirmed one a fresh link, and a
    // confirmed one the account-exists note. The answer is the same in every case.
    if (!account.enabled) return { ok: true };
    const sent = account.verified
      ? await sendAccountExists(account, baseUrl)
      : await sendVerification(account, baseUrl);
    return sent ? { ok: true } : { ok: false, code: EMAIL_SIGNUP_CODES.SEND_FAILED };
  } catch (error) {
    console.error('[email-signup] sign-up failed', error instanceof Error ? error.name : 'unknown');
    return { ok: false, code: EMAIL_SIGNUP_CODES.SEND_FAILED };
  }
}

/**
 * Send a new verification link to an address with an unconfirmed account.
 *
 * Answers `{ ok: true }` whether or not anything was sent (unknown, confirmed or disabled
 * addresses get nothing), so it cannot be used to probe for accounts.
 *
 * @param email The address the person signed up with.
 * @returns `{ ok: true }`, or a code for an unavailable feature, bad input or an exhausted budget.
 */
export async function resendSignupVerification(email: unknown): Promise<EmailSignupResult> {
  const baseUrl = publicBaseUrl();
  if (!isEmailSignupAvailable() || !baseUrl) {
    return { ok: false, code: EMAIL_SIGNUP_CODES.UNAVAILABLE };
  }
  if (!(await withinIpBudget())) return { ok: false, code: EMAIL_SIGNUP_CODES.RATE_LIMITED };
  const canonical = canonicalSignupEmail(email);
  if (!canonical) {
    return { ok: false, code: EMAIL_SIGNUP_CODES.INVALID, message: 'Enter a valid email address.' };
  }
  if (!withinAddressBudget(canonical)) return { ok: false, code: EMAIL_SIGNUP_CODES.RATE_LIMITED };

  try {
    const account = await findSignupAccount(canonical);
    if (account && account.enabled && !account.verified) await sendVerification(account, baseUrl);
  } catch (error) {
    console.error('[email-signup] resend failed', error instanceof Error ? error.name : 'unknown');
  }
  return { ok: true };
}

/**
 * Redeem a verification link.
 *
 * @param token The `token` parameter from the link.
 * @returns `valid` with a one-time sign-in code, or why the link was refused.
 */
export async function verifyEmailSignup(token: unknown): Promise<VerifyEmailSignupResult> {
  if (!isWellFormedVerificationToken(token)) return { state: 'invalid' };
  try {
    const redeemed = await redeemVerificationToken(hashVerificationToken(token));
    if (redeemed.state !== 'valid' || !redeemed.userId) {
      return { state: redeemed.state === 'valid' ? 'invalid' : redeemed.state };
    }
    // No tenant yet: the session starts workspace-less and the onboarding wizard takes over.
    const oneTimeCode = await insertAuthOneTimeCode(redeemed.userId, null);
    return { state: 'valid', oneTimeCode };
  } catch (error) {
    console.error('[email-signup] verification failed', error instanceof Error ? error.name : 'unknown');
    return { state: 'invalid' };
  }
}
