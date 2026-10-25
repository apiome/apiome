"use client";

import { useState } from 'react';
import { Mail, Lock, ShieldCheck, Zap, CreditCard, ArrowRight, RotateCcw } from 'lucide-react';
import { signIn } from '@lib/auth/session-client';
import { BrandMark } from '../components/brand';
import type { ProviderSummary } from '../../../lib/auth/provider-registry';
import { getProviderBrand } from '../components/auth/provider-brand';
import { AuthShell } from '../components/auth/AuthShell';
import { AuthField } from '../components/auth/AuthField';
import { BetaBadge } from '../components/auth/BetaBadge';
import LoginBrandPanel from './LoginBrandPanel';
import EnterpriseSsoSignIn from './EnterpriseSsoSignIn';
import { SSOButton } from './SSOButton';
import { LegalLine } from './LegalLine';
import type { LegalLinks } from '@lib/auth/signup-page';
import { getAuthErrorCopy } from './auth-error-copy';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Spinner } from '../components/ui/Spinner';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { VIDEO_WALKTHROUGHS_URL } from '@/app/components/ade/help/helpModel';

/**
 * The sign-in / create-account page (HIVE-4.1, #5295 — re-skin of OLO-3.1's layout).
 *
 * Authority: `docs/mockups/auth/login.html`, `docs/mockups/DESIGN.md` §2 and §7.
 *
 * The information architecture is unchanged from the page this replaces — SSO first,
 * credentials collapsed beneath an "or use your email" expander, one banner carrying the
 * 17 mapped auth error codes, a mode toggle at the foot. What changed is everything that
 * named a colour: the animated aurora blobs, the film grain and the glass card
 * (`login.module.css`) are gone, and the page is drawn from the Hive token layer instead —
 * so the front door now follows the reader's theme, density and font-scale like the rest of
 * the app, and carries the bee.
 *
 * The frame (hex canvas, brand panel, card column) is `components/auth/AuthShell`, shared
 * with the other signed-out screens.
 */

/** The three promises under the sign-in form. Icons are decorative; the words carry them. */
const TRUST_BADGES = [
  { icon: ShieldCheck, label: 'Secure' },
  { icon: Zap, label: 'Free to start' },
  { icon: CreditCard, label: 'No credit card' },
] as const;

/**
 * The field-level message shown under the password box after a rejected credentials attempt
 * (mockup § Adds). The banner says what happened; this says *where*.
 */
const CREDENTIALS_FIELD_ERROR = 'Incorrect email or password.';

/** No legal pages configured: the footer line is left out. */
const NO_LEGAL_LINKS: LegalLinks = { termsUrl: null, privacyUrl: null };

interface LoginClientProps {
  error?: string;
  /** Validated by the login page (resolveCallbackUrl) before being passed in. */
  callbackUrl?: string;
  /**
   * The deployment's enabled SSO providers (provider registry, OLO-2.3), resolved server-side
   * by the login page. Exactly one button renders per entry; an empty list hides the SSO block.
   * When any provider is listed, SSO is the primary path and the credentials form starts
   * collapsed beneath the "or" divider (OLO-3.1); with an empty list the form is the only path
   * and renders expanded.
   */
  ssoProviders?: ProviderSummary[];
  /**
   * Whether at least one enterprise SSO provider (a workspace's own SAML / OIDC IdP, EID-1.1) is
   * enabled with a verified domain. Adds "Sign in with SSO" beside the provider buttons, and like
   * them makes the credentials form start collapsed.
   */
  enterpriseSso?: boolean;
  /** The installation's Terms / Privacy pages, for the footer; left out when neither is set. */
  legalLinks?: LegalLinks;
}

const LoginClient: React.FC<LoginClientProps> = ({
  error,
  callbackUrl = '/ade',
  ssoProviders = [],
  enterpriseSso = false,
  legalLinks = NO_LEGAL_LINKS,
}) => {
  // Any non-credentials path — provider buttons or enterprise SSO — is the primary path (OLO-3.1).
  const hasPrimaryPath = ssoProviders.length > 0 || enterpriseSso;
  const [payload, setPayload] = useState<Record<string, string>>({
    email: '',
    password: '',
  });
  const [signInEnabled, setSignInEnabled] = useState(true);
  const [isSSOLoading, setIsSSOLoading] = useState(false);
  // SSO is the primary path (OLO-3.1): the credentials form starts collapsed beneath the "or"
  // divider whenever SSO buttons render. It starts expanded when credentials are the only path
  // (no enabled providers) or when the user just failed a credentials attempt and needs the
  // form back to retry. Expansion is one-way — the form never re-collapses.
  const [showCredentials, setShowCredentials] = useState(
    !hasPrimaryPath || error === 'CredentialsSignin'
  );
  // The rejected pair is marked on the fields themselves until the user edits either one —
  // an error the reader has already started fixing should stop shouting.
  const [credentialsRejected, setCredentialsRejected] = useState(error === 'CredentialsSignin');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSignInEnabled(false);
    // Sign-up has its own page (`/signup`, SGN-1.2); this form only signs in.
    signIn('credentials', {
      payload: JSON.stringify(payload),
      callbackUrl,
      redirect: true,
    }).finally(() => setSignInEnabled(true));
  };

  const handleSSOLogin = async (provider: string) => {
    setIsSSOLoading(true);
    try {
      await signIn(provider, { callbackUrl });
    } catch (error) {
      console.error('SSO sign-in error:', error);
      setIsSSOLoading(false);
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.name === 'email' || e.target.name === 'password') {
      setCredentialsRejected(false);
    }
    setPayload({
      ...payload,
      [e.target.name]: e.target.value,
    });
  }

  // Distinct guidance per structured auth error code (OLO-1.5) from the NextAuth error redirect,
  // rendered with per-code affordances (OLO-3.2). Unknown codes resolve to the safe generic
  // banner inside getAuthErrorCopy.
  const authErrorCopy = getAuthErrorCopy(error);
  const message = authErrorCopy;
  // "Try again" returns to a clean login page: the error param is dropped so the banner clears,
  // while the (already-validated) callbackUrl survives the round trip.
  const showRetry = Boolean(authErrorCopy?.retry);
  const retryHref = `/login?callbackUrl=${encodeURIComponent(callbackUrl)}`;
  // The banner's tone, and how insistently it is announced. An error interrupts a screen
  // reader (role="alert"); success and info wait their turn (role="status") — OLO-3.5.
  const isErrorMessage = message?.type === 'error';
  const bannerTone = message?.type === 'info' ? 'info' : 'danger';
  // Both boxes redden — the pair was rejected, not one of them — but the sentence is
  // printed once, under the password, exactly as the mockup's error variant has it.
  const fieldError = credentialsRejected ? CREDENTIALS_FIELD_ERROR : undefined;

  return (
    <AuthShell brand={<LoginBrandPanel />}>
      <Card data-testid="login-card" className="auth-card">
        {/* The bee and the beta chip, for the widths where the brand panel is hidden. CSS
            owns the swap, so exactly one copy of each is on screen at any width. */}
        <div className="auth-card__logo">
          <BrandMark variant="glyph" size={44} />
          <BetaBadge />
        </div>

        <h1 className="auth-title">Welcome back</h1>
        <p className="auth-sub mt-1">Sign in to continue to your workspace</p>
        {/* The channel, not one video: the old intro video's link stopped working. */}
        <p className="mt-2 text-xs text-fg-muted">
          New to Apiome?{' '}
          <a
            href={VIDEO_WALKTHROUGHS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="auth-link font-medium"
          >
            Explore our YouTube →
          </a>
        </p>

        {/* Message Display — per-code copy and affordances (OLO-3.2).
            Errors announce assertively via role="alert" so a screen reader interrupts
            with the failure; success/info updates stay polite (OLO-3.5, a11y). */}
        {message && (
          <Alert
            variant={bannerTone}
            role={isErrorMessage ? 'alert' : 'status'}
            aria-live={isErrorMessage ? 'assertive' : 'polite'}
            data-testid="login-banner"
            className="mt-4"
            actions={
              showRetry ? (
                <Button asChild variant="outline" size="sm" pill>
                  <a href={retryHref}>
                    <RotateCcw aria-hidden="true" />
                    Try again
                  </a>
                </Button>
              ) : undefined
            }
          >
            {message.text}
          </Alert>
        )}

        {/* SSO first — the primary path. One button per enabled provider (registry, OLO-2.3). */}
        {ssoProviders.length > 0 && (
          isSSOLoading ? (
            <Card variant="soft" className="auth-wait mt-5" role="status" aria-live="polite">
              {/* The tile is the live region; the spinner inside it is ornament, so it is
                  hidden rather than announcing a second time. */}
              <Spinner size="md" aria-hidden="true" />
              <div className="text-sm font-semibold text-fg">Connecting…</div>
              <div className="text-xs text-fg-muted">Redirecting to authentication provider</div>
            </Card>
          ) : (
            <div className="mt-5 flex flex-col gap-2">
              {ssoProviders.map((provider) => {
                const { Icon, iconClassName } = getProviderBrand(provider.id);
                return (
                  <SSOButton
                    key={provider.id}
                    provider={provider.label}
                    icon={<Icon size={ICON_SIZE.rail} className={iconClassName} />}
                    onClick={() => handleSSOLogin(provider.id)}
                  />
                );
              })}
            </div>
          )
        )}

        {/* Enterprise SSO (EID-1.1): the workspace's own IdP, found from the work email. */}
        {enterpriseSso && !isSSOLoading && (
          <div className={ssoProviders.length > 0 ? 'mt-2' : 'mt-5'}>
            <EnterpriseSsoSignIn callbackUrl={callbackUrl} disabled={!signInEnabled} />
          </div>
        )}

        {/* Divider (only when SSO renders above the email form). While the credentials
            form is collapsed it doubles as the expand control. */}
        {hasPrimaryPath && (
          showCredentials ? (
            <div className="auth-divider mt-5">or use your email</div>
          ) : (
            <button
              type="button"
              onClick={() => setShowCredentials(true)}
              disabled={isSSOLoading}
              aria-expanded={false}
              aria-controls="credentials-form"
              className="auth-divider mt-5"
            >
              or use your email
            </button>
          )
        )}

        {/* Credentials form — collapsed (hidden) until requested when SSO is available
            (OLO-3.1). Tailwind preflight gives [hidden] display:none, and hidden fields
            are neither focusable nor submittable, so the collapsed form is fully inert. */}
        <form
          id="credentials-form"
          hidden={!showCredentials}
          onSubmit={handleSubmit}
          className="mt-4 space-y-4"
        >

          <AuthField
            id="email"
            label="Email Address"
            icon={<Mail size={ICON_SIZE.dense} aria-hidden="true" />}
            type="email"
            name="email"
            value={payload['email']}
            onChange={handleChange}
            required
            autoComplete="email"
            placeholder="you@example.com"
            invalid={Boolean(fieldError)}
          />

          <AuthField
            id="password"
            label="Password"
            icon={<Lock size={ICON_SIZE.dense} aria-hidden="true" />}
            aside={
              <a href="#" className="auth-link text-xs font-medium">
                Forgot your password?
              </a>
            }
            type="password"
            name="password"
            value={payload['password']}
            onChange={handleChange}
            required
            autoComplete="current-password"
            placeholder="••••••••"
            error={fieldError}
          />


          <Button
            type="submit"
            variant="primary"
            size="lg"
            className="w-full"
            disabled={!signInEnabled || isSSOLoading}
          >
            Sign In
            <ArrowRight aria-hidden="true" />
          </Button>
        </form>

        {/* Sign-up has its own page (SGN-1.2). */}
        <p className="auth-sub mt-5 text-center">
          Don&apos;t have an account?{' '}
          <a href="/signup" className="auth-link font-semibold" data-testid="login-create-account">
            Create one
          </a>
        </p>

        {/* Trust Badges */}
        <div className="auth-trust mt-4">
          {TRUST_BADGES.map(({ icon: Icon, label }) => (
            <span key={label}>
              <Icon aria-hidden="true" />
              {label}
            </span>
          ))}
        </div>
      </Card>

      <LegalLine action="signing in" links={legalLinks} />
    </AuthShell>
  );
};

export default LoginClient;
