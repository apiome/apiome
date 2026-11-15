'use client';

/**
 * The reader email form — PCX-1.1 (#5889).
 *
 * Posts to `POST /v1/portal/{tenant}/auth/magic-link` **from the browser**, so apiome-rest's
 * per-address rate limit sees the reader's own address. Every well-formed request is a `202`; on it the
 * page moves to the **Check your email** state.
 */

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { requestMagicLink } from '../../../../lib/portal/api';
import { portalPath } from '../../../../lib/portal/session';

interface SignInFormProps {
  /** The portal. */
  tenantSlug: string;
  /** Where to land after signing in. */
  returnTo: string;
  /** The public REST root (`NEXT_PUBLIC_REST_API_BASE_URL`). */
  restBase: string;
}

export function SignInForm({ tenantSlug, returnTo, restBase }: SignInFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const outcome = await requestMagicLink(restBase, tenantSlug, email, returnTo);
    if (outcome.ok) {
      router.replace(portalPath('/portal/sign-in', { tenant: tenantSlug, return_to: returnTo, sent: '1' }));
      return;
    }
    setPending(false);
    if (outcome.kind === 'rate-limited') {
      setError(`Too many sign-in requests. Try again in ${outcome.retryAfterSeconds} seconds.`);
    } else if (outcome.kind === 'invalid') {
      setError(outcome.message);
    } else {
      setError('Sign-in is unavailable right now. Try again in a moment.');
    }
  }

  return (
    <form className="portal-form" onSubmit={onSubmit} noValidate data-testid="reader-sign-in-form">
      <label className="portal-label" htmlFor="reader-email">
        Email address
      </label>
      <input
        id="reader-email"
        className="portal-input"
        type="email"
        name="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@company.com"
      />
      <button className="portal-button" type="submit" disabled={pending || !email.trim()}>
        {pending ? 'Sending…' : 'Email me a sign-in link'}
      </button>
      {error ? (
        <p className="portal-notice portal-notice-danger" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
