'use client';

/**
 * "Check your email" — what follows a sign-up (SGN-1.1, #5650).
 *
 * Shown for every accepted sign-up, whether the address was new or already had an account: the
 * difference is only in the email that arrives, so this screen reveals nothing. **Resend email**
 * asks for a fresh link (`resendSignupVerification`, rate-limited per address); **Use a different
 * email** returns to the form.
 */

import { useState } from 'react';
import { MailCheck, RotateCcw } from 'lucide-react';

import { resendSignupVerification } from '@lib/auth/email-signup-actions';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { getAuthErrorCopy } from './auth-error-copy';

/** Props for {@link SignupCheckEmail}. */
export interface SignupCheckEmailProps {
  /** The address the link went to, as the person typed it. */
  email: string;
  /** Back to the sign-up form. */
  onStartOver?: () => void;
}

/** What the resend button last did. */
type ResendState = { kind: 'idle' } | { kind: 'busy' } | { kind: 'sent' } | { kind: 'error'; text: string };

/**
 * The check-your-email panel.
 *
 * @param props See {@link SignupCheckEmailProps}.
 * @returns The panel.
 */
export function SignupCheckEmail({ email, onStartOver }: SignupCheckEmailProps) {
  const [resend, setResend] = useState<ResendState>({ kind: 'idle' });

  const handleResend = async () => {
    setResend({ kind: 'busy' });
    try {
      const result = await resendSignupVerification(email);
      setResend(
        result.ok
          ? { kind: 'sent' }
          : { kind: 'error', text: result.message ?? getAuthErrorCopy(result.code)?.text ?? 'Try again.' }
      );
    } catch {
      setResend({ kind: 'error', text: 'Something went wrong. Try again.' });
    }
  };

  return (
    <div data-testid="signup-check-email">
      <span className="auth-icon" aria-hidden="true">
        <MailCheck />
      </span>
      <h1 className="auth-title mt-4">Check your email</h1>
      {/* A `div`, not a `p`: the unlayered `p { color }` rule would override the utility ink. */}
      <div className="auth-sub mt-1">
        We sent a link to <strong className="text-fg">{email}</strong>. Open it to confirm your address
        and finish creating your account. The link works once and expires in 24 hours.
      </div>
      <div className="auth-sub mt-3">Nothing there? Check your spam folder, or send a new link.</div>

      {resend.kind === 'sent' && (
        <Alert variant="ok" role="status" className="mt-4" data-testid="signup-resend-sent">
          If that address is waiting to be confirmed, a new link is on its way.
        </Alert>
      )}
      {resend.kind === 'error' && (
        <Alert variant="danger" role="alert" className="mt-4" data-testid="signup-resend-error">
          {resend.text}
        </Alert>
      )}

      <div className="mt-5 flex flex-col gap-2">
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="w-full"
          onClick={handleResend}
          disabled={resend.kind === 'busy'}
          data-testid="signup-resend"
        >
          <RotateCcw aria-hidden="true" />
          {resend.kind === 'busy' ? 'Sending…' : 'Resend email'}
        </Button>
        {onStartOver && (
          <Button type="button" variant="link" onClick={onStartOver} data-testid="signup-start-over">
            Use a different email
          </Button>
        )}
      </div>
    </div>
  );
}

export default SignupCheckEmail;
