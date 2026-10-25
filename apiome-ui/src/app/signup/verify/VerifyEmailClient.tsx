'use client';

/**
 * The sign-up confirmation screen (SGN-1.1, #5650).
 *
 * Asks for the password the person chose when they signed up, then redeems the link
 * (`verifyEmailSignup`). The password is what ties the link to *their* sign-up: a link sent because
 * someone else signed up with the address cannot be completed without that someone's password, and
 * a completed link makes the entered password the account's only credential (RC6 security review —
 * account pre-hijacking). Then:
 *
 * - **valid** — "Email confirmed", and the one-time code is exchanged for a session
 *   (`signIn('credentials', { payload: { oneTimeCode } })`, the OAuth sign-up path). `/ade` then
 *   shows the first-tenant onboarding wizard, since the account has no workspace yet.
 * - **password-mismatch** — the form says so and stays; the link still works.
 * - **expired**, **used** or **invalid** — says which, and offers **Resend email** for the address
 *   plus a way to sign in. A used link is refused rather than signing in again.
 */

import { useState } from 'react';
import { CircleAlert, Lock, Mail, MailCheck, RotateCcw } from 'lucide-react';

import { resendSignupVerification, verifyEmailSignup, type VerifyEmailSignupResult } from '@lib/auth/email-signup-actions';
import { signIn } from '@lib/auth/session-client';
import { AuthShell } from '@/app/components/auth/AuthShell';
import { AuthField } from '@/app/components/auth/AuthField';
import { BetaBadge } from '@/app/components/auth/BetaBadge';
import { BrandMark } from '@/app/components/brand';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';
import { Spinner } from '@/app/components/ui/Spinner';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { getAuthErrorCopy } from '@/app/login/auth-error-copy';

/** Props for {@link VerifyEmailClient}. */
export interface VerifyEmailClientProps {
  /** The `token` query parameter; empty when the link had none. */
  token: string;
  /**
   * Skip redemption and show this result (docs fixtures and tests only). Never set by the page.
   * @internal
   */
  initialResult?: VerifyEmailSignupResult;
}

/** Where a confirmed account goes; the onboarding guard takes over from there. */
const AFTER_VERIFY = '/ade';

/** A link the page cannot redeem: why, with the way out. */
type RefusedState = Exclude<VerifyEmailSignupResult['state'], 'valid' | 'password-mismatch'>;

/** What the confirm form says when the password does not belong to this link's sign-up. */
export const PASSWORD_MISMATCH_TEXT =
  "That is not the password chosen for this sign-up. If you signed up more than once, use the link in your newest email — or sign up again.";

/** Heading and sentence per refused state. */
const REFUSED_COPY: Record<RefusedState, { title: string; text: string }> = {
  expired: {
    title: 'This link has expired',
    text: 'Confirmation links work for 24 hours. Enter your email address and we will send a new one.',
  },
  used: {
    title: 'This link was already used',
    text: 'Each confirmation link works once. If you confirmed your email, sign in. Otherwise, send a new link.',
  },
  invalid: {
    title: 'This link does not work',
    text: 'It may be incomplete or replaced by a newer email. Enter your email address and we will send a new one.',
  },
};

/**
 * The verification screen.
 *
 * @param props See {@link VerifyEmailClientProps}.
 * @returns The page body inside the auth shell.
 */
export default function VerifyEmailClient({ token, initialResult }: VerifyEmailClientProps) {
  const [result, setResult] = useState<VerifyEmailSignupResult | null>(
    initialResult ?? (token ? null : { state: 'invalid' })
  );
  const [signInFailed, setSignInFailed] = useState(false);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const handleConfirm = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    const redeemed = await verifyEmailSignup({ token, password }).catch(
      (): VerifyEmailSignupResult => ({ state: 'invalid' })
    );
    setBusy(false);
    setResult(redeemed);
    if (redeemed.state === 'valid') {
      // `signIn` resolves with nothing and navigates itself: to AFTER_VERIFY on success, to the login
      // error page on a refused code. Only a thrown error leaves the person here to sign in by hand.
      // (Treating the empty result as a failure flashed "We could not sign you in" on every sign-up.)
      await signIn('credentials', {
        payload: JSON.stringify({ oneTimeCode: redeemed.oneTimeCode }),
        callbackUrl: AFTER_VERIFY,
        redirect: true,
      }).catch(() => setSignInFailed(true));
    }
  };

  return (
    <AuthShell>
      <div className="auth-brandbar">
        <BrandMark variant="lockup" size={36} className="auth-brand__lockup" priority />
        <BetaBadge />
      </div>
      <Card className="auth-card" data-testid="signup-verify-card">
        {!result || result.state === 'password-mismatch' ? (
          <form onSubmit={handleConfirm} data-testid="signup-verify-confirm">
            <span className="auth-icon" aria-hidden="true">
              <Mail />
            </span>
            <h1 className="auth-title mt-4">Confirm your email</h1>
            <div className="auth-sub mt-1">
              Enter the password you chose when you signed up to finish creating your account.
            </div>
            {result?.state === 'password-mismatch' ? (
              <Alert variant="danger" role="alert" className="mt-4" data-testid="signup-verify-password-mismatch">
                {PASSWORD_MISMATCH_TEXT}
              </Alert>
            ) : null}
            <div className="mt-5 space-y-4">
              <AuthField
                id="verify-password"
                label="Password"
                icon={<Lock size={ICON_SIZE.dense} aria-hidden="true" />}
                type="password"
                name="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoComplete="current-password"
                placeholder="••••••••"
              />
              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={busy || password.length === 0}
                title={password.length === 0 ? 'Enter your password first' : undefined}
                data-testid="signup-verify-submit"
              >
                {busy ? <Spinner size="sm" aria-hidden="true" /> : null}
                {busy ? 'Confirming…' : 'Confirm and sign in'}
              </Button>
            </div>
          </form>
        ) : result.state === 'valid' ? (
          <Confirmed signInFailed={signInFailed} />
        ) : (
          <Refused state={result.state} />
        )}
      </Card>
    </AuthShell>
  );
}

/**
 * The confirmed state: the sign-in is already under way.
 *
 * @param props.signInFailed The session exchange failed; offer the sign-in page instead.
 * @returns The confirmed panel.
 */
function Confirmed({ signInFailed }: { signInFailed: boolean }) {
  return (
    <div data-testid="signup-verified">
      <span className="auth-icon" aria-hidden="true">
        <MailCheck />
      </span>
      <h1 className="auth-title mt-4">Email confirmed</h1>
      <div className="auth-sub mt-1">
        Your account is ready. Next, name your workspace — it takes a minute.
      </div>
      {signInFailed ? (
        <Alert variant="info" role="status" className="mt-4" data-testid="signup-verified-sign-in">
          We could not sign you in automatically. Sign in with your email and password to continue.
        </Alert>
      ) : (
        <div className="auth-wait mt-5" role="status" aria-live="polite">
          <Spinner size="md" aria-hidden="true" />
          <div className="text-sm font-semibold text-fg">Signing you in…</div>
        </div>
      )}
      <Button asChild variant={signInFailed ? 'primary' : 'link'} size="lg" className="mt-4 w-full">
        <a href={signInFailed ? '/login' : AFTER_VERIFY}>{signInFailed ? 'Sign in' : 'Continue'}</a>
      </Button>
    </div>
  );
}

/**
 * A refused link: why, a resend form and a sign-in link.
 *
 * @param props.state Which refusal.
 * @returns The refused panel.
 */
function Refused({ state }: { state: RefusedState }) {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<{ kind: 'idle' | 'busy' | 'sent' } | { kind: 'error'; text: string }>({
    kind: 'idle',
  });
  const copy = REFUSED_COPY[state];

  const handleResend = async (event: React.FormEvent) => {
    event.preventDefault();
    setStatus({ kind: 'busy' });
    try {
      const sent = await resendSignupVerification(email);
      setStatus(
        sent.ok
          ? { kind: 'sent' }
          : { kind: 'error', text: sent.message ?? getAuthErrorCopy(sent.code)?.text ?? 'Try again.' }
      );
    } catch {
      setStatus({ kind: 'error', text: 'Something went wrong. Try again.' });
    }
  };

  return (
    <div data-testid={`signup-verify-${state}`}>
      <span className="auth-icon" aria-hidden="true">
        <CircleAlert />
      </span>
      <h1 className="auth-title mt-4">{copy.title}</h1>
      <div className="auth-sub mt-1">{copy.text}</div>

      {status.kind === 'sent' && (
        <Alert variant="ok" role="status" className="mt-4" data-testid="signup-resend-sent">
          If that address is waiting to be confirmed, a new link is on its way.
        </Alert>
      )}
      {status.kind === 'error' && (
        <Alert variant="danger" role="alert" className="mt-4" data-testid="signup-resend-error">
          {status.text}
        </Alert>
      )}

      <form className="mt-5 space-y-4" onSubmit={handleResend}>
        <AuthField
          id="verify-resend-email"
          label="Email address"
          icon={<Mail size={ICON_SIZE.dense} aria-hidden="true" />}
          type="email"
          name="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          autoComplete="email"
          placeholder="you@example.com"
        />
        <Button
          type="submit"
          variant="outline"
          size="lg"
          className="w-full"
          disabled={status.kind === 'busy'}
          data-testid="signup-resend"
        >
          <RotateCcw aria-hidden="true" />
          {status.kind === 'busy' ? 'Sending…' : 'Resend email'}
        </Button>
      </form>
      <p className="auth-sub mt-5 text-center">
        Already confirmed?{' '}
        <a href="/login" className="auth-link font-semibold">
          Sign in
        </a>
      </p>
    </div>
  );
}
