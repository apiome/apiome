'use client';

import { useState } from 'react';
import { ArrowRight, Building2, Mail } from 'lucide-react';

import { signInWithSso } from '@lib/auth/better-auth-client-compat';
import { AuthField } from '../components/auth/AuthField';
import { Button } from '../components/ui/Button';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';

/**
 * "Sign in with SSO" on the sign-in page (EID-1.1, #5011).
 *
 * A workspace's own identity provider (SAML 2.0 or OIDC) is found from the email domain: the user
 * types their work email, and Better Auth's SSO plugin sends them to the IdP registered for that
 * domain. Starts as one button beside the other providers; pressing it reveals the email field so
 * the page does not grow a second form until someone asks for it. Email-first routing (the page
 * choosing SSO from the email typed in the main form) is EID-1.2.
 */

/** What the inline message says when no enabled provider covers the domain. */
export const SSO_NO_PROVIDER_MESSAGE = 'No single sign-on is set up for this email domain.';
/** What it says when sign-on could not start for any other reason. */
export const SSO_START_FAILED_MESSAGE = 'Single sign-on could not start. Try again.';

/** Props for {@link EnterpriseSsoSignIn}. */
export interface EnterpriseSsoSignInProps {
  /** Where to land after signing in (validated by the page). */
  callbackUrl: string;
  /** Disables the control while another sign-in is in flight. */
  disabled?: boolean;
  /** Told when a redirect to the IdP starts, so the page can disable its other paths. */
  onStart?: () => void;
}

/**
 * The SSO entry: a button, then a work-email field and "Continue with SSO".
 *
 * @param props See {@link EnterpriseSsoSignInProps}.
 * @returns The control.
 */
export default function EnterpriseSsoSignIn({ callbackUrl, disabled = false, onStart }: EnterpriseSsoSignInProps) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | undefined>(undefined);

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="auth-sso"
        onClick={() => setOpen(true)}
        disabled={disabled}
        aria-expanded={false}
        aria-controls="enterprise-sso-form"
        data-testid="enterprise-sso-open"
      >
        <span aria-hidden="true" className="auth-sso__mark">
          <Building2 size={ICON_SIZE.rail} />
        </span>
        <span className="font-semibold">Sign in with SSO</span>
        <ArrowRight className="auth-sso__arrow" aria-hidden="true" />
      </Button>
    );
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(undefined);
    setBusy(true);
    onStart?.();
    const outcome = await signInWithSso(email, callbackUrl);
    if (outcome === 'redirecting') return; // the browser is leaving for the IdP
    setBusy(false);
    setMessage(outcome === 'no-provider' ? SSO_NO_PROVIDER_MESSAGE : SSO_START_FAILED_MESSAGE);
  };

  return (
    <form
      id="enterprise-sso-form"
      className="space-y-3"
      onSubmit={submit}
      data-testid="enterprise-sso-form"
      aria-label="Sign in with SSO"
    >
      <AuthField
        id="sso-email"
        label="Work email"
        icon={<Mail size={ICON_SIZE.dense} aria-hidden="true" />}
        type="email"
        name="sso-email"
        value={email}
        onChange={(e) => {
          setEmail(e.target.value);
          setMessage(undefined);
        }}
        required
        autoComplete="email"
        autoFocus
        placeholder="you@company.com"
        error={message}
      />
      <Button
        type="submit"
        variant="primary"
        size="lg"
        className="w-full"
        disabled={disabled || busy || email.trim() === ''}
        data-testid="enterprise-sso-continue"
      >
        {busy ? 'Redirecting…' : 'Continue with SSO'}
        <ArrowRight aria-hidden="true" />
      </Button>
    </form>
  );
}
