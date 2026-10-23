'use client';

/**
 * The sign-up confirmation screen (SGN-1.1, #5650).
 *
 * Redeems the link's token once (`verifyEmailSignup`), then:
 *
 * - **valid** — "Email confirmed", and the one-time code is exchanged for a session
 *   (`signIn('credentials', { payload: { oneTimeCode } })`, the OAuth sign-up path). `/ade` then
 *   shows the first-tenant onboarding wizard, since the account has no workspace yet.
 * - **expired**, **used** or **invalid** — says which, and offers **Resend email** for the address
 *   plus a way to sign in. A used link is refused rather than signing in again.
 *
 * The redemption runs once per mount even under React Strict Mode's double effect: a second call
 * would find the link already used and show the wrong state.
 */

import { useEffect, useRef, useState } from 'react';
import { CircleAlert, Mail, MailCheck, RotateCcw } from 'lucide-react';

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

/** Heading and sentence per refused state. */
const REFUSED_COPY: Record<Exclude<VerifyEmailSignupResult['state'], 'valid'>, { title: string; text: string }> = {
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
  const [result, setResult] = useState<VerifyEmailSignupResult | null>(initialResult ?? null);
  const [signInFailed, setSignInFailed] = useState(false);
  const started = useRef(Boolean(initialResult));

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      const redeemed = await verifyEmailSignup(token).catch(
        (): VerifyEmailSignupResult => ({ state: 'invalid' })
      );
      setResult(redeemed);
      if (redeemed.state === 'valid') {
        const outcome = await signIn('credentials', {
          payload: JSON.stringify({ oneTimeCode: redeemed.oneTimeCode }),
          callbackUrl: AFTER_VERIFY,
          redirect: true,
        }).catch(() => null);
        if (!outcome || (outcome as { error?: unknown }).error) setSignInFailed(true);
      }
    })();
  }, [token]);

  return (
    <AuthShell>
      <div className="auth-brandbar">
        <BrandMark variant="lockup" size={36} className="auth-brand__lockup" priority />
        <BetaBadge />
      </div>
      <Card className="auth-card" data-testid="signup-verify-card">
        {!result ? (
          <div className="auth-wait" role="status" aria-live="polite" data-testid="signup-verifying">
            <Spinner size="md" aria-hidden="true" />
            <div className="text-sm font-semibold text-fg">Confirming your email…</div>
          </div>
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
function Refused({ state }: { state: Exclude<VerifyEmailSignupResult['state'], 'valid'> }) {
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
