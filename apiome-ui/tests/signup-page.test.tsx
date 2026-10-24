/**
 * The `/signup` page (SGN-1.2, #5651): every enabled provider then the email form, each policy
 * state with its own copy and no control that cannot work, the allowed-domain hint, the
 * provider hand-off, the sign-in link and the legal line. Also dumps the docs fixtures.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockSignIn = jest.fn();

jest.mock('@lib/auth/email-signup-actions', () => ({
  startEmailSignup: jest.fn(),
  resendSignupVerification: jest.fn(),
  verifyEmailSignup: jest.fn(),
}));
jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  signIn: (...args: unknown[]) => mockSignIn(...args),
}));
jest.mock('@/app/hooks/useDarkMode', () => ({ useDarkMode: () => false }));

import SignupClient, {
  PROVIDER_START_FAILED,
  PROVIDER_START_RATE_LIMITED,
} from '../src/app/signup/SignupClient';
import {
  SIGNUP_CLOSED_NOTICE,
  SIGNUP_INVITE_ONLY_NOTICE,
  signupPageState,
  type LegalLinks,
} from '../lib/auth/signup-page';
import type { ProviderSummary } from '../lib/auth/provider-registry';
import type { SignupPolicy } from '../lib/auth/signup-policy';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const PROVIDERS = [
  { id: 'github', label: 'GitHub', enabled: true },
  { id: 'google', label: 'Google', enabled: true },
] as unknown as ProviderSummary[];

const OPEN: SignupPolicy = { mode: 'open', allowedEmailDomains: [], source: 'db' };
const LEGAL: LegalLinks = { termsUrl: 'https://apiome.dev/terms', privacyUrl: 'https://apiome.dev/privacy' };
const NO_LEGAL: LegalLinks = { termsUrl: null, privacyUrl: null };

const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;

beforeEach(() => {
  jest.clearAllMocks();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ success: true }) });
  mockSignIn.mockResolvedValue(undefined);
});

/**
 * Render the page for a policy.
 *
 * @param policy The installation policy.
 * @param options Providers, email availability and legal links.
 * @returns The render result.
 */
function renderPage(
  policy: SignupPolicy = OPEN,
  options: { providers?: ProviderSummary[]; email?: boolean; legal?: LegalLinks } = {}
) {
  return render(
    <SignupClient
      providers={options.providers ?? PROVIDERS}
      state={signupPageState(policy, options.email ?? true)}
      legalLinks={options.legal ?? LEGAL}
    />
  );
}

describe('/signup — an open installation', () => {
  it('lists every enabled provider, then the email form, then the sign-in link', () => {
    renderPage();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Create your account');
    expect(screen.getByRole('button', { name: 'Sign up with GitHub' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign up with Google' })).toBeInTheDocument();
    expect(screen.getByText('or use your email')).toBeInTheDocument();
    expect(screen.getByTestId('email-signup-form')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
    expect(screen.getByTestId('legal-line')).toHaveTextContent(
      'By creating an account, you agree to our Terms of Service and Privacy Policy'
    );
  });

  it('starts a provider sign-up: records the intent, then hands off to the provider', async () => {
    renderPage();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sign up with GitHub' }));
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/signup-intent',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ provider: 'github' }) })
    );
    expect(mockSignIn).toHaveBeenCalledWith('github', { callbackUrl: '/ade' });
  });

  it('says so, and stays put, when a provider sign-up cannot be started', async () => {
    fetchMock.mockResolvedValue({ ok: false, json: async () => ({}) });
    renderPage();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sign up with Google' }));
    });
    expect(screen.getByTestId('signup-error')).toHaveTextContent(PROVIDER_START_FAILED);
    expect(mockSignIn).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Sign up with Google' })).toBeInTheDocument();
  });

  it('names the rate limit when this network has started too many sign-ups (SGN-1.5)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 429, json: async () => ({ code: 'auth-rate-limited' }) });
    renderPage();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sign up with GitHub' }));
    });
    expect(screen.getByTestId('signup-error')).toHaveTextContent(PROVIDER_START_RATE_LIMITED);
    expect(mockSignIn).not.toHaveBeenCalled();
  });

  it('names the allowed email domains when the policy restricts them', () => {
    renderPage({ ...OPEN, allowedEmailDomains: ['northwind.io', 'contoso.example'] });
    expect(screen.getByTestId('signup-domains')).toHaveTextContent(
      'Sign-up is open to addresses at northwind.io and contoso.example.'
    );
  });

  it('says email sign-up is unavailable, with no form, when no mail sender is configured', () => {
    renderPage(OPEN, { email: false });
    expect(screen.queryByTestId('email-signup-form')).not.toBeInTheDocument();
    expect(screen.getByTestId('email-signup-unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign up with GitHub' })).toBeInTheDocument();
  });

  it('draws no divider when there are no providers, only the email form', () => {
    renderPage(OPEN, { providers: [] });
    expect(screen.queryByText('or use your email')).not.toBeInTheDocument();
    expect(screen.getByTestId('email-signup-form')).toBeInTheDocument();
  });

  it('leaves the legal line out when the installation has no legal pages', () => {
    renderPage(OPEN, { legal: NO_LEGAL });
    expect(screen.queryByTestId('legal-line')).not.toBeInTheDocument();
  });
});

describe('/signup — closed and invite-only installations', () => {
  it.each([
    ['closed', SIGNUP_CLOSED_NOTICE],
    ['invite_only', SIGNUP_INVITE_ONLY_NOTICE],
  ] as const)('a %s installation shows its own notice and no control that cannot work', (mode, notice) => {
    renderPage({ mode, allowedEmailDomains: ['northwind.io'], source: 'db' });
    const shown = screen.getByTestId(`signup-notice-${mode}`);
    expect(shown).toHaveTextContent(notice.title);
    expect(shown).toHaveTextContent(notice.text);
    expect(screen.queryByRole('button', { name: /^Sign up with/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId('email-signup-form')).not.toBeInTheDocument();
    expect(screen.queryByTestId('signup-domains')).not.toBeInTheDocument();
    // The one thing left to do is sign in.
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});

describe('/signup — accessibility and docs fixtures', () => {
  it('renders the docs fixtures `signup` and `signup-closed`, axe-clean', async () => {
    const open = renderPage({ ...OPEN, allowedEmailDomains: ['northwind.io'] });
    writeA11yFixture('signup', open.container.innerHTML);
    expect(await axe(open.container)).toHaveNoViolations();
    open.unmount();

    const closed = renderPage({ mode: 'closed', allowedEmailDomains: [], source: 'db' });
    writeA11yFixture('signup-closed', closed.container.innerHTML);
    expect(await axe(closed.container)).toHaveNoViolations();
  });
});
