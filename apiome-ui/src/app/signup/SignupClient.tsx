'use client';

/**
 * The `/signup` page body (SGN-1.2, #5651).
 *
 * One card on the AuthShell, in reading order:
 *
 * 1. **Create your account**, and — when the policy restricts sign-up to some email domains —
 *    a line naming them.
 * 2. One **Sign up with …** button per enabled provider. Each records a sign-up intent
 *    (`POST /api/auth/signup-intent`) and starts that provider's redirect, exactly as the
 *    login page's sign-up mode did before this page existed.
 * 3. **or use your email**, then the email + password form from SGN-1.1 — or, when no mail
 *    sender is configured, a note that email sign-up is unavailable.
 * 4. **Already have an account? Sign in**, and the legal line when the installation has
 *    Terms / Privacy pages.
 *
 * A closed or invite-only installation replaces 1–3's controls with its notice (see
 * `lib/auth/signup-page.ts`): nothing on the page can be pressed that would not work.
 * After an accepted email sign-up the card becomes **Check your email** (SGN-1.1).
 */

import { useState } from 'react';

import type { ProviderSummary } from '@lib/auth/provider-registry';
import { signIn } from '@lib/auth/session-client';
import { allowedDomainsHint, type LegalLinks, type SignupPageState } from '@lib/auth/signup-page';
import { AuthShell } from '@/app/components/auth/AuthShell';
import { BetaBadge } from '@/app/components/auth/BetaBadge';
import { getProviderBrand } from '@/app/components/auth/provider-brand';
import { BrandMark } from '@/app/components/brand';
import { Alert } from '@/app/components/ui/Alert';
import { Card } from '@/app/components/ui/Card';
import { Spinner } from '@/app/components/ui/Spinner';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { getAuthErrorCopy } from '@/app/login/auth-error-copy';
import EmailSignupForm from '@/app/login/EmailSignupForm';
import { LegalLine } from '@/app/login/LegalLine';
import LoginBrandPanel from '@/app/login/LoginBrandPanel';
import SignupCheckEmail from '@/app/login/SignupCheckEmail';
import { SSOButton } from '@/app/login/SSOButton';

/** Where a new account lands once a provider sign-up completes. */
const AFTER_SIGNUP = '/ade';

/** What the page says when a provider's sign-up could not be started. */
export const PROVIDER_START_FAILED = 'Could not start sign-up. Please try again.';

/** What the page says when this network has started too many sign-ups (SGN-1.5, HTTP 429). */
export const PROVIDER_START_RATE_LIMITED =
  'Too many sign-up attempts from your network. Wait a minute, then try again.';

/** Props for {@link SignupClient}. */
export interface SignupClientProps {
  /** The enabled sign-in providers — the same list the login page shows. */
  providers: readonly ProviderSummary[];
  /** What the policy lets this page offer (`signupPageState`). */
  state: SignupPageState;
  /** The installation's Terms / Privacy pages. */
  legalLinks: LegalLinks;
  /** The public Turnstile site key when the email form carries a CAPTCHA (SGN-1.5); else null. */
  turnstileSiteKey?: string | null;
}

/**
 * The sign-up card.
 *
 * @param props See {@link SignupClientProps}.
 * @returns The page body inside the auth shell.
 */
export default function SignupClient({
  providers,
  state,
  legalLinks,
  turnstileSiteKey = null,
}: SignupClientProps) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkEmailFor, setCheckEmailFor] = useState<string | null>(null);

  const domainsHint = allowedDomainsHint(state.allowedDomains);
  const showProviders = state.showProviders && providers.length > 0;
  const showEmailBlock = state.showEmailForm || state.showEmailUnavailable;

  /**
   * Record the sign-up intent and hand off to the provider.
   *
   * @param providerId The provider registry id.
   */
  const startProvider = async (providerId: string) => {
    setStarting(true);
    setError(null);
    try {
      const response = await fetch('/api/auth/signup-intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: providerId }),
      });
      if (!response.ok) {
        setError(response.status === 429 ? PROVIDER_START_RATE_LIMITED : PROVIDER_START_FAILED);
        setStarting(false);
        return;
      }
      await signIn(providerId, { callbackUrl: AFTER_SIGNUP });
    } catch (caught) {
      console.error('[signup] provider sign-up failed to start', caught);
      setError(PROVIDER_START_FAILED);
      setStarting(false);
    }
  };

  return (
    <AuthShell brand={<LoginBrandPanel />}>
      <Card data-testid="signup-card" className="auth-card" data-mode={state.mode}>
        {/* The bee and the beta chip, for the widths where the brand panel is hidden. */}
        <div className="auth-card__logo">
          <BrandMark variant="glyph" size={44} />
          <BetaBadge />
        </div>

        {checkEmailFor ? (
          <SignupCheckEmail email={checkEmailFor} onStartOver={() => setCheckEmailFor(null)} />
        ) : (
          <>
            <h1 className="auth-title">Create your account</h1>
            <p className="auth-sub mt-1">Join thousands of developers building with Apiome</p>

            {state.notice ? (
              <Alert
                variant="info"
                role="status"
                className="mt-5"
                data-testid={`signup-notice-${state.mode}`}
              >
                <strong className="block font-semibold">{state.notice.title}</strong>
                {state.notice.text}
              </Alert>
            ) : null}

            {domainsHint ? (
              <div className="auth-sub mt-2" data-testid="signup-domains">
                {domainsHint}
              </div>
            ) : null}

            {error ? (
              <Alert variant="danger" role="alert" className="mt-4" data-testid="signup-error">
                {error}
              </Alert>
            ) : null}

            {showProviders ? (
              starting ? (
                <Card variant="soft" className="auth-wait mt-5" role="status" aria-live="polite">
                  <Spinner size="md" aria-hidden="true" />
                  <div className="text-sm font-semibold text-fg">Connecting…</div>
                  <div className="text-xs text-fg-muted">Redirecting to authentication provider</div>
                </Card>
              ) : (
                <div className="mt-5 flex flex-col gap-2" data-testid="signup-providers">
                  {providers.map((provider) => {
                    const { Icon, iconClassName } = getProviderBrand(provider.id);
                    return (
                      <SSOButton
                        key={provider.id}
                        provider={provider.label}
                        icon={<Icon size={ICON_SIZE.rail} className={iconClassName} />}
                        onClick={() => void startProvider(provider.id)}
                        isSignUp
                      />
                    );
                  })}
                </div>
              )
            ) : null}

            {showProviders && showEmailBlock ? (
              <div className="auth-divider mt-5">or use your email</div>
            ) : null}

            {state.showEmailForm ? (
              <EmailSignupForm
                disabled={starting}
                onSubmitted={setCheckEmailFor}
                turnstileSiteKey={turnstileSiteKey}
              />
            ) : null}

            {state.showEmailUnavailable ? (
              <Alert variant="info" role="status" className="mt-4" data-testid="email-signup-unavailable">
                {getAuthErrorCopy('email-signup-unavailable')?.text}
              </Alert>
            ) : null}
          </>
        )}

        <p className="auth-sub mt-5 text-center">
          Already have an account?{' '}
          <a href="/login" className="auth-link font-semibold" data-testid="signup-sign-in">
            Sign in
          </a>
        </p>
      </Card>

      <LegalLine action="creating an account" links={legalLinks} />
    </AuthShell>
  );
}
