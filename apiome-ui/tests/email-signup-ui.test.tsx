/**
 * Email sign-up screens (SGN-1.1, #5650): the `/signup` page's email form (SGN-1.2), the no-sender
 * notice and check-your-email, and `/signup/verify` (confirmed, expired, used, invalid). Also dumps
 * the docs fixtures `signup-form`, `signup-check-email` and `signup-verified`.
 */
import React, { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockStartEmailSignup = jest.fn();
const mockResend = jest.fn();
const mockVerify = jest.fn();
const mockSignIn = jest.fn();

jest.mock('@lib/auth/email-signup-actions', () => ({
  startEmailSignup: (...args: unknown[]) => mockStartEmailSignup(...args),
  resendSignupVerification: (...args: unknown[]) => mockResend(...args),
  verifyEmailSignup: (...args: unknown[]) => mockVerify(...args),
}));
jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  signIn: (...args: unknown[]) => mockSignIn(...args),
}));
jest.mock('@lib/auth/better-auth-client-compat', () => ({ signInWithSso: jest.fn() }));
jest.mock('@/app/hooks/useDarkMode', () => ({ useDarkMode: () => false }));

import SignupClient from '../src/app/signup/SignupClient';
import { signupPageState } from '../lib/auth/signup-page';
import VerifyEmailClient from '../src/app/signup/verify/VerifyEmailClient';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const TOKEN = 'a'.repeat(43);

beforeEach(() => {
  jest.clearAllMocks();
  mockSignIn.mockResolvedValue({ ok: true });
});

const OPEN = { mode: 'open' as const, allowedEmailDomains: [], source: 'db' as const };
const NO_LEGAL = { termsUrl: null, privacyUrl: null };

/** The `/signup` page with no providers, and email sign-up on or off. */
function renderSignup(emailSignupAvailable = true) {
  return render(
    <SignupClient providers={[]} state={signupPageState(OPEN, emailSignupAvailable)} legalLinks={NO_LEGAL} />
  );
}

/** Fill and submit the email sign-up form. */
async function submitSignup(email = 'ada@example.com') {
  fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Ada Lovelace' } });
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: email } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Analytical1' } });
  await act(async () => {
    fireEvent.click(screen.getByTestId('email-signup-submit'));
  });
}

describe('the email form with Turnstile (SGN-1.5)', () => {
  const SITE_KEY = '1x00000000000000000000AA';
  let issueToken: ((token: string) => void) | null = null;
  const turnstile = {
    render: jest.fn((_el: HTMLElement, options: { sitekey: string; callback: (token: string) => void }) => {
      issueToken = options.callback;
      return 'widget-1';
    }),
    reset: jest.fn(),
    remove: jest.fn(),
  };

  beforeEach(() => {
    issueToken = null;
    (window as unknown as { turnstile?: unknown }).turnstile = turnstile;
  });
  afterEach(() => {
    delete (window as unknown as { turnstile?: unknown }).turnstile;
  });

  /** The page with the CAPTCHA on. */
  const renderWithCaptcha = () =>
    render(
      <SignupClient
        providers={[]}
        state={signupPageState(OPEN, true)}
        legalLinks={NO_LEGAL}
        turnstileSiteKey={SITE_KEY}
      />
    );

  it('draws the check and holds Create account until it passes', async () => {
    renderWithCaptcha();
    await waitFor(() => expect(turnstile.render).toHaveBeenCalled());
    expect(turnstile.render.mock.calls[0][1]).toMatchObject({ sitekey: SITE_KEY, theme: 'auto' });
    expect(screen.getByTestId('email-signup-submit')).toBeDisabled();

    act(() => issueToken?.('tok-1'));
    expect(screen.getByTestId('email-signup-submit')).toBeEnabled();
  });

  it('sends the token, and resets the check after a refusal', async () => {
    mockStartEmailSignup.mockResolvedValue({ ok: false, code: 'email-signup-captcha-failed' });
    renderWithCaptcha();
    await waitFor(() => expect(turnstile.render).toHaveBeenCalled());
    act(() => issueToken?.('tok-1'));

    await submitSignup();

    expect(mockStartEmailSignup).toHaveBeenCalledWith(expect.objectContaining({ captchaToken: 'tok-1' }));
    expect(screen.getByTestId('email-signup-error')).toHaveTextContent('We could not confirm the security check.');
    expect(turnstile.reset).toHaveBeenCalledWith('widget-1');
    // The used token is gone, so the button waits for a fresh one.
    expect(screen.getByTestId('email-signup-submit')).toBeDisabled();
  });

  it('shows the disposable-address message', async () => {
    mockStartEmailSignup.mockResolvedValue({ ok: false, code: 'email-signup-disposable-domain' });
    renderSignup();
    await submitSignup('bot@mailinator.com');
    expect(screen.getByTestId('email-signup-error')).toHaveTextContent(
      'Addresses from disposable email services cannot be used to sign up.'
    );
  });

  it('draws no check when Turnstile is off', () => {
    renderSignup();
    expect(screen.queryByTestId('signup-turnstile')).not.toBeInTheDocument();
    expect(screen.getByTestId('email-signup-submit')).toBeEnabled();
  });
});

describe('the email form on /signup', () => {
  it('offers name, email and password with the password rules as a hint', () => {
    renderSignup();
    expect(screen.getByTestId('email-signup-form')).toBeVisible();
    expect(screen.getByText(/At least 8 characters · One uppercase and one lowercase letter/)).toBeInTheDocument();
    // The legacy request form's extra field is gone.
    expect(screen.queryByLabelText(/How did you hear about us/)).not.toBeInTheDocument();
  });

  it('says so, with no form, when no email sender is configured', () => {
    renderSignup(false);
    expect(screen.queryByTestId('email-signup-form')).not.toBeInTheDocument();
    expect(screen.getByTestId('email-signup-unavailable')).toHaveTextContent(
      'Sign-up with an email address is not available on this server.'
    );
  });

  it('shows "Check your email" after an accepted sign-up, then resends on request', async () => {
    mockStartEmailSignup.mockResolvedValue({ ok: true });
    mockResend.mockResolvedValue({ ok: true });
    renderSignup();
    await submitSignup('ada@example.com');

    expect(mockStartEmailSignup).toHaveBeenCalledWith({
      name: 'Ada Lovelace',
      email: 'ada@example.com',
      password: 'Analytical1',
    });
    const panel = screen.getByTestId('signup-check-email');
    expect(panel).toHaveTextContent('Check your email');
    expect(panel).toHaveTextContent('We sent a link to ada@example.com.');

    await act(async () => {
      fireEvent.click(screen.getByTestId('signup-resend'));
    });
    expect(mockResend).toHaveBeenCalledWith('ada@example.com');
    expect(screen.getByTestId('signup-resend-sent')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('signup-start-over'));
    expect(screen.getByTestId('email-signup-form')).toBeInTheDocument();
  });

  it('shows the server’s sentence for invalid input and the policy copy for a refusal', async () => {
    mockStartEmailSignup.mockResolvedValueOnce({
      ok: false,
      code: 'email-signup-invalid',
      message: 'Password must contain at least one uppercase letter.',
    });
    renderSignup();
    await submitSignup();
    expect(screen.getByTestId('email-signup-error')).toHaveTextContent(
      'Password must contain at least one uppercase letter.'
    );

    mockStartEmailSignup.mockResolvedValueOnce({ ok: false, code: 'signup-disabled' });
    await submitSignup();
    expect(screen.getByTestId('email-signup-error')).toHaveTextContent('New account sign-ups are currently disabled');
    expect(screen.queryByTestId('signup-check-email')).not.toBeInTheDocument();
  });

  it('renders the docs fixtures `signup-form` and `signup-check-email`, axe-clean', async () => {
    mockStartEmailSignup.mockResolvedValue({ ok: true });
    const { container } = renderSignup();
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Ada Lovelace' } });
    screen.getByLabelText('Full name').setAttribute('value', 'Ada Lovelace');
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'ada@example.com' } });
    screen.getByLabelText('Email address').setAttribute('value', 'ada@example.com');
    writeA11yFixture('signup-form', container.innerHTML);
    expect(await axe(container)).toHaveNoViolations();

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Analytical1' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('email-signup-submit'));
    });
    writeA11yFixture('signup-check-email', container.innerHTML);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('/signup/verify', () => {
  it('confirms a valid link once, even under Strict Mode, and signs in with the one-time code', async () => {
    mockVerify.mockResolvedValue({ state: 'valid', oneTimeCode: 'code-1' });
    render(
      <StrictMode>
        <VerifyEmailClient token={TOKEN} />
      </StrictMode>
    );
    expect(await screen.findByTestId('signup-verified')).toHaveTextContent('Email confirmed');
    expect(mockVerify).toHaveBeenCalledTimes(1);
    expect(mockVerify).toHaveBeenCalledWith(TOKEN);
    await waitFor(() =>
      expect(mockSignIn).toHaveBeenCalledWith('credentials', {
        payload: JSON.stringify({ oneTimeCode: 'code-1' }),
        callbackUrl: '/ade',
        redirect: true,
      })
    );
  });

  it('offers the sign-in page when the session exchange fails', async () => {
    mockVerify.mockResolvedValue({ state: 'valid', oneTimeCode: 'code-1' });
    mockSignIn.mockResolvedValue({ error: 'CredentialsSignin' });
    render(<VerifyEmailClient token={TOKEN} />);
    expect(await screen.findByTestId('signup-verified-sign-in')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
  });

  it.each([
    ['expired', 'This link has expired'],
    ['used', 'This link was already used'],
    ['invalid', 'This link does not work'],
  ] as const)('refuses an %s link with a resend form and never signs in', async (state, title) => {
    mockVerify.mockResolvedValue({ state });
    mockResend.mockResolvedValue({ ok: true });
    render(<VerifyEmailClient token={TOKEN} />);
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
    expect(mockSignIn).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'ada@example.com' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('signup-resend'));
    });
    expect(mockResend).toHaveBeenCalledWith('ada@example.com');
    expect(screen.getByTestId('signup-resend-sent')).toBeInTheDocument();
  });

  it('shows the rate-limit copy when a resend is refused', async () => {
    mockResend.mockResolvedValue({ ok: false, code: 'email-signup-rate-limited' });
    render(<VerifyEmailClient token={TOKEN} initialResult={{ state: 'expired' }} />);
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'ada@example.com' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('signup-resend'));
    });
    expect(screen.getByTestId('signup-resend-error')).toHaveTextContent('Too many sign-up attempts');
  });

  it('renders the docs fixtures `signup-verified` and `signup-verify-expired`, axe-clean', async () => {
    const verified = render(<VerifyEmailClient token={TOKEN} initialResult={{ state: 'valid', oneTimeCode: 'c' }} />);
    expect(mockVerify).not.toHaveBeenCalled();
    writeA11yFixture('signup-verified', verified.container.innerHTML);
    expect(await axe(verified.container)).toHaveNoViolations();
    verified.unmount();

    const expired = render(<VerifyEmailClient token={TOKEN} initialResult={{ state: 'expired' }} />);
    writeA11yFixture('signup-verify-expired', expired.container.innerHTML);
    expect(await axe(expired.container)).toHaveNoViolations();
  });
});
