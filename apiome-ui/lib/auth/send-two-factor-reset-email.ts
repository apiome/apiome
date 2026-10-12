/**
 * The email a user receives when an administrator resets their two-factor (TFA-1.2, #5656).
 *
 * A reset removes a protection from someone's account and signs them out everywhere, so they are
 * told — both because they asked for it and need to know it is done, and because if they did
 * *not* ask for it they need to know that too.
 *
 * The message says what happened and what to do next. It deliberately does not carry the reason
 * the administrator gave (an internal note, written for the audit trail) or name who did it.
 *
 * Sent through the same SendGrid configuration as the two-factor email code
 * (`send-two-factor-email-otp.ts`). An installation without a sender simply does not send it:
 * the reset has already happened, and the caller tells the administrator so they can pass the
 * word on themselves.
 */

import sgMail from '@sendgrid/mail';
import {
  EMAIL_FROM_ENV,
  SENDGRID_API_KEY_ENV,
  isTwoFactorEmailOtpConfigured,
} from './send-two-factor-email-otp';

/** Who the message is for. */
export interface TwoFactorResetRecipient {
  email?: string | null;
  name?: string | null;
}

/** The message, ready for a mail client. */
export interface TwoFactorResetMessage {
  subject: string;
  text: string;
  html: string;
}

/**
 * Escape a value for use in HTML text.
 *
 * @param value The raw text.
 * @returns The text with `&`, `<`, `>` and quotes escaped.
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
 * Compose the reset message.
 *
 * @param recipient The user whose two-factor was reset; only their name is used, for the greeting.
 * @returns The subject and the plain-text and HTML bodies.
 */
export function buildTwoFactorResetMessage(recipient: TwoFactorResetRecipient): TwoFactorResetMessage {
  const name = recipient.name?.trim();
  const greeting = name ? `Hello ${name},` : 'Hello,';
  const lines = [
    'An administrator reset the two-factor authentication on your apiome account.',
    'Your authenticator app and backup codes no longer work for this account, and you have been signed out on every device.',
    'Sign in as usual — you will not be asked for a code — then set two-factor up again from Profile, under Security.',
    'If you did not ask for this, contact your administrator straight away.',
  ];
  return {
    subject: 'Your apiome two-factor authentication was reset',
    text: [greeting, ...lines].join('\n\n'),
    html: [greeting, ...lines].map((line) => `<p>${escapeHtml(line)}</p>`).join(''),
  };
}

/**
 * Tell a user their two-factor was reset.
 *
 * Never throws: the reset this reports has already been committed, so a delivery problem must not
 * turn a successful reset into a failed request. The outcome is returned instead.
 *
 * @param recipient The user to tell.
 * @param env Environment map; defaults to `process.env` (injectable for tests).
 * @returns `true` when the message was handed to SendGrid; `false` when no sender is configured,
 *   the user has no email address, or the send failed.
 */
export async function sendTwoFactorResetEmail(
  recipient: TwoFactorResetRecipient,
  env: NodeJS.Dict<string> = process.env
): Promise<boolean> {
  const to = recipient.email?.trim();
  if (!to || !isTwoFactorEmailOtpConfigured(env)) return false;

  sgMail.setApiKey(env[SENDGRID_API_KEY_ENV]!.trim());
  try {
    await sgMail.send({ to, from: env[EMAIL_FROM_ENV]!.trim(), ...buildTwoFactorResetMessage(recipient) });
    return true;
  } catch (error) {
    console.error(
      '[2fa-reset-email] SendGrid send failed',
      error instanceof Error ? error.name : 'unknown'
    );
    return false;
  }
}
