/**
 * The stable codes email sign-up answers with (SGN-1.1, #5650), beyond the SGN-1.4 policy codes.
 *
 * Kept in their own dependency-free module so the browser form can import them without pulling the
 * server-only parts of `email-signup.ts` (Node `crypto`, the mail sender) into the client bundle.
 * Each has login-page copy in `src/app/login/auth-error-copy.ts`.
 */

/** Stable codes a sign-up or resend may answer with. */
export const EMAIL_SIGNUP_CODES = {
  /** No mail sender or no public base URL: email sign-up is off on this installation. */
  UNAVAILABLE: 'email-signup-unavailable',
  /** The name, email or password failed validation (the message says which). */
  INVALID: 'email-signup-invalid',
  /** Too many sign-up or resend requests from this client or for this address. */
  RATE_LIMITED: 'email-signup-rate-limited',
  /** The mail sender refused the message. */
  SEND_FAILED: 'email-signup-send-failed',
} as const;

/** One of {@link EMAIL_SIGNUP_CODES}. */
export type EmailSignupCode = (typeof EMAIL_SIGNUP_CODES)[keyof typeof EMAIL_SIGNUP_CODES];
