/**
 * Profile two-factor settings for an account without a password (TFA-1.1, #5655).
 *
 * An account that signs in only through a provider has no password to gate enrolment on. The
 * three wizards — enable, disable, regenerate backup codes — ask it to confirm by a recent
 * sign-in instead: nothing more when it has just signed in, and a "Sign in again with …" button
 * when it has not. `two-factor-settings.test.tsx` covers the account that has a password.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TwoFactorSettings } from '@/app/ade/dashboard/profile/TwoFactorSettings';

const mockEnable = jest.fn();
const mockDisable = jest.fn();
const mockVerifyTotp = jest.fn();
const mockGenerateBackupCodes = jest.fn();
const mockUpdate = jest.fn(async () => {});
const mockUseAuthSession = jest.fn();
const mockSignIn = jest.fn();
const mockGetTwoFactorReauthStatus = jest.fn();

jest.mock('@lib/auth/auth-client', () => ({
  authClient: {
    twoFactor: {
      enable: (...args: unknown[]) => mockEnable(...args),
      disable: (...args: unknown[]) => mockDisable(...args),
      verifyTotp: (...args: unknown[]) => mockVerifyTotp(...args),
      generateBackupCodes: (...args: unknown[]) => mockGenerateBackupCodes(...args),
    },
  },
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => mockUseAuthSession(),
  signIn: (...args: unknown[]) => mockSignIn(...args),
}));

jest.mock('@lib/auth/two-factor-profile-actions', () => ({
  getBackupCodeStatus: jest.fn(async () => ({ remaining: 8 })),
  getTrustedDeviceStatus: jest.fn(async () => ({ trusted: false })),
  revokeThisTrustedDevice: jest.fn(async () => ({ ok: true })),
  getEmailOtpAvailability: jest.fn(async () => ({ available: false })),
  getTwoFactorReauthStatus: (...args: unknown[]) => mockGetTwoFactorReauthStatus(...args),
}));

jest.mock('react-qr-code', () => ({
  __esModule: true,
  default: ({ value }: { value: string }) => <div data-testid="qr-mock">{value}</div>,
}));

const GITHUB = { id: 'github', label: 'GitHub' };
const GOOGLE = { id: 'google', label: 'Google' };

/** Set the session's enrolment flag. */
const signedIn = (twoFactorEnabled: boolean) =>
  mockUseAuthSession.mockReturnValue({
    data: { user: { user_id: 'u1', email: 'a@b.co', twoFactorEnabled }, expires: '', twoFactorElevated: twoFactorEnabled },
    update: mockUpdate,
  });

/** Render the card for a passwordless account and wait for its status to load. */
async function mount(status: { fresh: boolean; providers?: { id: string; label: string }[] }) {
  mockGetTwoFactorReauthStatus.mockResolvedValue({
    hasPassword: false,
    fresh: status.fresh,
    providers: status.providers ?? [GITHUB],
  });
  render(<TwoFactorSettings />);
  await waitFor(() => expect(mockGetTwoFactorReauthStatus).toHaveBeenCalled());
  // Let the resolved status reach state before the dialogs are opened.
  await screen.findByTestId('two-factor-settings');
  await waitFor(() => undefined);
}

beforeEach(() => {
  jest.clearAllMocks();
  signedIn(false);
});

describe('enable — signed in a moment ago', () => {
  it('asks for no password and starts enrolment', async () => {
    mockEnable.mockResolvedValue({
      data: { totpURI: 'otpauth://totp/apiome:a@b.co?secret=ABC', backupCodes: ['ab12c-de34f'] },
      error: null,
    });
    await mount({ fresh: true });

    fireEvent.click(screen.getByTestId('two-factor-enable-open'));

    expect(await screen.findByTestId('two-factor-reauth-fresh')).toHaveTextContent(
      'This account has no password. You signed in a moment ago, so nothing more is needed to confirm it is you.'
    );
    expect(screen.queryByTestId('two-factor-enroll-password')).not.toBeInTheDocument();
    // The stepper names what the reader actually does.
    expect(screen.getByTestId('two-factor-enroll-stepper')).toHaveTextContent("Confirm it's you");
    expect(screen.getByTestId('two-factor-enroll-stepper')).not.toHaveTextContent('Confirm password');

    fireEvent.click(screen.getByTestId('two-factor-enroll-continue'));

    await waitFor(() => {
      // No password is sent — not even an empty one.
      expect(mockEnable).toHaveBeenCalledWith({});
      expect(screen.getByTestId('two-factor-qr')).toBeInTheDocument();
    });
  });

  it('switches to "sign in again" when the server says the session has gone stale', async () => {
    mockEnable.mockResolvedValue({
      data: null,
      error: { code: 'REAUTH_REQUIRED', message: 'Sign in again to confirm it is you.', status: 403 },
    });
    await mount({ fresh: true });

    fireEvent.click(screen.getByTestId('two-factor-enable-open'));
    fireEvent.click(await screen.findByTestId('two-factor-enroll-continue'));

    expect(await screen.findByTestId('two-factor-reauth-required')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-reauth-github')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-enroll-continue')).toBeDisabled();
    expect(screen.queryByTestId('two-factor-qr')).not.toBeInTheDocument();
  });

  it('shows any other refusal as it is', async () => {
    mockEnable.mockResolvedValue({ data: null, error: { code: 'SOMETHING', message: 'Try later.' } });
    await mount({ fresh: true });

    fireEvent.click(screen.getByTestId('two-factor-enable-open'));
    fireEvent.click(await screen.findByTestId('two-factor-enroll-continue'));

    expect(await screen.findByText('Try later.')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-reauth-fresh')).toBeInTheDocument();
  });
});

describe('enable — signed in too long ago', () => {
  it('holds the change and offers to sign in again with the linked provider', async () => {
    await mount({ fresh: false });

    fireEvent.click(screen.getByTestId('two-factor-enable-open'));

    const notice = await screen.findByTestId('two-factor-reauth-required');
    expect(notice).toHaveTextContent(
      'This account has no password, so confirm it is you by signing in again. You can change two-factor settings for 10 minutes after you sign in.'
    );
    expect(screen.getByTestId('two-factor-enroll-continue')).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Sign in again with GitHub' }));

    // Back to this page, with a session the server will accept as fresh.
    expect(mockSignIn).toHaveBeenCalledWith('github', { callbackUrl: window.location.pathname });
    expect(mockEnable).not.toHaveBeenCalled();
  });

  it('offers every linked provider', async () => {
    await mount({ fresh: false, providers: [GITHUB, GOOGLE] });
    fireEvent.click(screen.getByTestId('two-factor-enable-open'));

    expect(await screen.findByRole('button', { name: 'Sign in again with GitHub' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in again with Google' }));
    expect(mockSignIn).toHaveBeenCalledWith('google', { callbackUrl: window.location.pathname });
  });

  it('says what to do when no linked provider can be offered', async () => {
    await mount({ fresh: false, providers: [] });
    fireEvent.click(screen.getByTestId('two-factor-enable-open'));

    expect(await screen.findByTestId('two-factor-reauth-required')).toHaveTextContent(
      'Sign out, then sign in again and come back to this page.'
    );
    expect(screen.queryByRole('button', { name: /Sign in again with/ })).not.toBeInTheDocument();
  });
});

describe('disable', () => {
  beforeEach(() => signedIn(true));

  it('turns two-factor off with no password when the sign-in is recent', async () => {
    mockDisable.mockResolvedValue({ data: { status: true }, error: null });
    await mount({ fresh: true });

    fireEvent.click(screen.getByTestId('two-factor-disable-open'));
    expect(await screen.findByTestId('two-factor-reauth-fresh')).toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-disable-password')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('two-factor-disable-confirm'));

    await waitFor(() => expect(mockDisable).toHaveBeenCalledWith({}));
    expect(mockUpdate).toHaveBeenCalled();
  });

  it('cannot be confirmed from a stale session', async () => {
    await mount({ fresh: false });

    fireEvent.click(screen.getByTestId('two-factor-disable-open'));

    expect(await screen.findByTestId('two-factor-reauth-required')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-disable-confirm')).toBeDisabled();
    expect(mockDisable).not.toHaveBeenCalled();
  });
});

describe('regenerate backup codes', () => {
  beforeEach(() => signedIn(true));

  it('issues new codes with no password when the sign-in is recent', async () => {
    mockGenerateBackupCodes.mockResolvedValue({ data: { backupCodes: ['zz99y-xx88w'] }, error: null });
    await mount({ fresh: true });

    fireEvent.click(await screen.findByTestId('two-factor-regen-open'));
    expect(await screen.findByTestId('two-factor-reauth-fresh')).toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-regen-password')).not.toBeInTheDocument();
    expect(screen.getByTestId('two-factor-regen-stepper')).toHaveTextContent("Confirm it's you");

    fireEvent.click(screen.getByTestId('two-factor-regen-confirm'));

    await waitFor(() => expect(mockGenerateBackupCodes).toHaveBeenCalledWith({}));
    expect(await screen.findByTestId('two-factor-backup-codes')).toHaveTextContent('zz99y-xx88w');
  });

  it('cannot be confirmed from a stale session', async () => {
    await mount({ fresh: false });

    fireEvent.click(await screen.findByTestId('two-factor-regen-open'));

    expect(await screen.findByTestId('two-factor-reauth-required')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-regen-confirm')).toBeDisabled();
  });
});

describe('an account with a password', () => {
  it('is asked for it exactly as before', async () => {
    mockGetTwoFactorReauthStatus.mockResolvedValue({ hasPassword: true, fresh: false, providers: [GITHUB] });
    render(<TwoFactorSettings />);
    await waitFor(() => expect(mockGetTwoFactorReauthStatus).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId('two-factor-enable-open'));

    expect(await screen.findByTestId('two-factor-enroll-password')).toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-reauth-fresh')).not.toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-reauth-required')).not.toBeInTheDocument();
    expect(screen.getByTestId('two-factor-enroll-stepper')).toHaveTextContent('Confirm password');
  });

  it('keeps asking for the password when the status cannot be read', async () => {
    mockGetTwoFactorReauthStatus.mockRejectedValue(new Error('offline'));
    render(<TwoFactorSettings />);
    await waitFor(() => expect(mockGetTwoFactorReauthStatus).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId('two-factor-enable-open'));
    expect(await screen.findByTestId('two-factor-enroll-password')).toBeInTheDocument();
  });
});
