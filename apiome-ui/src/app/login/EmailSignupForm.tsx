'use client';

/**
 * The email + password sign-up form (SGN-1.1, #5650).
 *
 * Name, email and password, checked against the same password rules the server enforces
 * (`lib/auth/password-policy.ts`; the hint lists them). Submitting calls `startEmailSignup`; on
 * success the parent swaps in {@link SignupCheckEmail}. A refusal from the sign-up policy, the
 * rate limit or the mail sender renders the login page's copy for its code.
 *
 * When the installation configures Cloudflare Turnstile (SGN-1.5, #5654), a security check sits
 * above **Create account**; the button waits for its token, and every submission resets it, because
 * a token works once.
 *
 * SGN-1.2 mounts this same form on the `/signup` page; until then it is the login page's
 * **Create one** mode.
 */

import { useState } from 'react';
import { ArrowRight, Lock, Mail, User } from 'lucide-react';

import { startEmailSignup } from '@lib/auth/email-signup-actions';
import { EMAIL_SIGNUP_CODES } from '@lib/auth/email-signup-codes';
import { PASSWORD_REQUIREMENTS } from '@/app/components/ade/account/passwordStrength';
import { AuthField } from '../components/auth/AuthField';
import { TurnstileWidget } from '../components/auth/TurnstileWidget';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { getAuthErrorCopy } from './auth-error-copy';

/** Props for {@link EmailSignupForm}. */
export interface EmailSignupFormProps {
  /** Called with the address once the server says to check email. */
  onSubmitted: (email: string) => void;
  /** Disables the form while another sign-in path is running. */
  disabled?: boolean;
  /** `id` for the `<form>`, so a disclosure control can point at it. */
  id?: string;
  /** Hides the form (collapsed beneath the provider buttons). */
  hidden?: boolean;
  /** The public Turnstile site key when CAPTCHA is on; null or absent draws no check. */
  turnstileSiteKey?: string | null;
}

/** The password hint: the server's three rules, in the order the profile dialog lists them. */
const PASSWORD_HINT = PASSWORD_REQUIREMENTS.map((requirement) => requirement.label).join(' · ');

/**
 * The sign-up form.
 *
 * @param props See {@link EmailSignupFormProps}.
 * @returns The form, with its own error banner.
 */
export function EmailSignupForm({
  onSubmitted,
  disabled = false,
  id,
  hidden,
  turnstileSiteKey = null,
}: EmailSignupFormProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = useState(0);

  const waitingForCaptcha = Boolean(turnstileSiteKey) && !captchaToken;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await startEmailSignup({
        name,
        email,
        password,
        ...(turnstileSiteKey ? { captchaToken } : {}),
      });
      if (turnstileSiteKey) setCaptchaReset((count) => count + 1);
      if (result.ok) {
        onSubmitted(email.trim());
        return;
      }
      setError(
        result.code === EMAIL_SIGNUP_CODES.INVALID && result.message
          ? result.message
          : (getAuthErrorCopy(result.code)?.text ?? 'Something went wrong. Try again.')
      );
    } catch (caught) {
      console.error('[EmailSignupForm] sign-up failed', caught);
      if (turnstileSiteKey) setCaptchaReset((count) => count + 1);
      setError('Something went wrong. Try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form id={id} hidden={hidden} onSubmit={handleSubmit} className="mt-4 space-y-4" data-testid="email-signup-form">
      {error && (
        <Alert variant="danger" role="alert" data-testid="email-signup-error">
          {error}
        </Alert>
      )}
      <AuthField
        id="signup-name"
        label="Full name"
        icon={<User size={ICON_SIZE.dense} aria-hidden="true" />}
        type="text"
        name="name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        maxLength={255}
        autoComplete="name"
        placeholder="Ada Lovelace"
      />
      <AuthField
        id="signup-email"
        label="Email address"
        icon={<Mail size={ICON_SIZE.dense} aria-hidden="true" />}
        type="email"
        name="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        required
        maxLength={254}
        autoComplete="email"
        placeholder="you@example.com"
      />
      <AuthField
        id="signup-password"
        label="Password"
        icon={<Lock size={ICON_SIZE.dense} aria-hidden="true" />}
        type="password"
        name="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        required
        minLength={8}
        autoComplete="new-password"
        placeholder="••••••••"
        hint={PASSWORD_HINT}
      />
      {turnstileSiteKey ? (
        <TurnstileWidget siteKey={turnstileSiteKey} onToken={setCaptchaToken} resetKey={captchaReset} />
      ) : null}
      <Button
        type="submit"
        variant="primary"
        size="lg"
        className="w-full"
        disabled={busy || disabled || waitingForCaptcha}
        data-testid="email-signup-submit"
      >
        {busy ? 'Creating account…' : 'Create account'}
        <ArrowRight aria-hidden="true" />
      </Button>
    </form>
  );
}

export default EmailSignupForm;
