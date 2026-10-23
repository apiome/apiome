/**
 * SendGrid delivery for the email sign-up messages (SGN-1.1, #5650).
 *
 * Uses the same sender as two-factor email (`SENDGRID_API_KEY`, `EMAIL_FROM`). Never logs the
 * message body: the verification email carries a live sign-in link.
 */

import sgMail from '@sendgrid/mail';

import type { SignupEmailMessage } from './email-signup';
import { EMAIL_FROM_ENV, SENDGRID_API_KEY_ENV } from './send-two-factor-email-otp';

/**
 * Send one sign-up email.
 *
 * @param to Recipient address.
 * @param message From `buildVerificationEmail` or `buildAccountExistsEmail`.
 * @param env Environment map; defaults to `process.env`.
 * @returns `true` once SendGrid accepted the message; `false` when unconfigured or refused.
 */
export async function sendSignupEmail(
  to: string,
  message: SignupEmailMessage,
  env: NodeJS.Dict<string> = process.env
): Promise<boolean> {
  const apiKey = env[SENDGRID_API_KEY_ENV]?.trim();
  const from = env[EMAIL_FROM_ENV]?.trim();
  const recipient = to?.trim();
  if (!apiKey || !from || !recipient) return false;

  sgMail.setApiKey(apiKey);
  try {
    await sgMail.send({ to: recipient, from, ...message });
    return true;
  } catch (error) {
    console.error('[email-signup] SendGrid send failed', error instanceof Error ? error.name : 'unknown');
    return false;
  }
}
