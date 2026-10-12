/**
 * Login 2FA step — backup codes, trusted devices and lockout (OLO-9.14, #5006).
 *
 * The three things the second step could not do before: redeem a backup code when the device
 * is lost, remember this browser for thirty days, and say plainly when the factor is locked.
 * The server side of each is Better Auth's `twoFactor` plugin; these tests pin what the screen
 * sends it and what it does with the answer. `login-two-factor.test.tsx` covers the flow that
 * was already there.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import TwoFactorClient from '@/app/login/2fa/TwoFactorClient';
import {
  TWO_FACTOR_CALLBACK_STORAGE_KEY,
  TWO_FACTOR_METHODS_STORAGE_KEY,
} from '@lib/auth/two-factor-callback';

const mockVerifyTotp = jest.fn();
const mockVerifyOtp = jest.fn();
const mockVerifyBackupCode = jest.fn();
const mockSendOtp = jest.fn();
const mockBrowserNavigate = jest.fn();

jest.mock('@lib/auth/auth-client', () => ({
  authClient: {
    twoFactor: {
      verifyTotp: (...args: unknown[]) => mockVerifyTotp(...args),
      verifyOtp: (...args: unknown[]) => mockVerifyOtp(...args),
      verifyBackupCode: (...args: unknown[]) => mockVerifyBackupCode(...args),
      sendOtp: (...args: unknown[]) => mockSendOtp(...args),
    },
  },
}));

jest.mock('@lib/auth/browser-navigate', () => ({
  browserNavigate: (...args: unknown[]) => mockBrowserNavigate(...args),
}));

jest.mock('@/app/hooks/useDarkMode', () => ({
  useDarkMode: () => false,
}));

const OK = { data: { token: 'ok' }, error: null };
const BACKUP_CODE = 'ab12c-de34f';

/** Type a full authenticator code and submit the form that is showing. */
const submitTotp = (code = '123456') => {
  fireEvent.change(screen.getByTestId('two-factor-totp-code'), { target: { value: code } });
  fireEvent.submit(screen.getByTestId('two-factor-card').querySelector('form')!);
};

/** Switch the card to the backup-code form. */
const openBackupForm = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByTestId('two-factor-toggle-backup'));
  return screen.getByTestId('two-factor-backup-code');
};

beforeEach(() => {
  jest.clearAllMocks();
  window.sessionStorage.clear();
});

describe('backup code redemption', () => {
  it('offers the recovery path from the verification form', () => {
    render(<TwoFactorClient callbackUrl="/ade" />);
    expect(screen.getByTestId('two-factor-toggle-backup')).toHaveTextContent(
      'Lost your device? Use a backup code'
    );
    expect(screen.queryByTestId('two-factor-backup-code')).not.toBeInTheDocument();
  });

  it('signs in with a backup code and leaves for the stored callback', async () => {
    window.sessionStorage.setItem(TWO_FACTOR_CALLBACK_STORAGE_KEY, '/ade/dashboard');
    mockVerifyBackupCode.mockResolvedValue(OK);
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    const field = await openBackupForm(user);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Use a backup code');
    expect(screen.queryByTestId('two-factor-totp-code')).not.toBeInTheDocument();

    fireEvent.change(field, { target: { value: BACKUP_CODE } });
    await user.click(screen.getByTestId('two-factor-backup-submit'));

    await waitFor(() =>
      expect(mockVerifyBackupCode).toHaveBeenCalledWith({ code: BACKUP_CODE, trustDevice: false })
    );
    await waitFor(() => expect(mockBrowserNavigate).toHaveBeenCalledWith('/ade/dashboard'));
    expect(mockVerifyTotp).not.toHaveBeenCalled();
    // The challenge is spent with the code: nothing is left behind for a later visit.
    expect(window.sessionStorage.getItem(TWO_FACTOR_CALLBACK_STORAGE_KEY)).toBeNull();
  });

  it('tidies a pasted code and keeps its case', async () => {
    mockVerifyBackupCode.mockResolvedValue(OK);
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    const field = await openBackupForm(user);
    fireEvent.change(field, { target: { value: ' Ab12C dE34f\n' } });
    expect(field).toHaveValue('Ab12C-dE34f');

    await user.click(screen.getByTestId('two-factor-backup-submit'));
    await waitFor(() =>
      expect(mockVerifyBackupCode).toHaveBeenCalledWith({ code: 'Ab12C-dE34f', trustDevice: false })
    );
  });

  it('keeps submit disabled until the code is whole, and never sends a partial one', async () => {
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    const field = await openBackupForm(user);
    const submit = screen.getByTestId('two-factor-backup-submit');
    expect(submit).toBeDisabled();

    fireEvent.change(field, { target: { value: 'ab12c-de3' } });
    expect(submit).toBeDisabled();
    fireEvent.submit(field.closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a whole backup code');
    expect(mockVerifyBackupCode).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: BACKUP_CODE } });
    expect(submit).toBeEnabled();
  });

  it('says a used or wrong code was not accepted, and lets the reader try another', async () => {
    mockVerifyBackupCode.mockResolvedValue({
      data: null,
      error: { code: 'INVALID_BACKUP_CODE', message: 'Invalid backup code', status: 401 },
    });
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    const field = await openBackupForm(user);
    fireEvent.change(field, { target: { value: BACKUP_CODE } });
    await user.click(screen.getByTestId('two-factor-backup-submit'));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That backup code was not accepted. Each code works once — check it and try another.'
    );
    expect(field).toBeEnabled();
    expect(mockBrowserNavigate).not.toHaveBeenCalled();
  });

  it('returns to the verification code, dropping what was typed and what was wrong', async () => {
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    const field = await openBackupForm(user);
    fireEvent.change(field, { target: { value: 'ab12' } });
    fireEvent.submit(field.closest('form')!);
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    expect(screen.getByTestId('two-factor-toggle-backup')).toHaveTextContent(
      'Use a verification code instead'
    );
    await user.click(screen.getByTestId('two-factor-toggle-backup'));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByTestId('two-factor-totp-code')).toHaveValue('');
    await user.click(screen.getByTestId('two-factor-toggle-backup'));
    expect(screen.getByTestId('two-factor-backup-code')).toHaveValue('');
  });

  it('is offered beside the method switcher when the challenge has two methods', async () => {
    window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['totp', 'otp']));
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    expect(screen.getByTestId('two-factor-method-switcher')).toBeInTheDocument();
    await openBackupForm(user);
    // The switcher belongs to the challenge's methods; the recovery form replaces it.
    expect(screen.queryByTestId('two-factor-method-switcher')).not.toBeInTheDocument();
  });
});

describe('trusted device', () => {
  it('is off by default and names how long the trust lasts', () => {
    render(<TwoFactorClient callbackUrl="/ade" />);
    const box = screen.getByRole('checkbox', { name: /Trust this device for 30 days/ });
    expect(box).not.toBeChecked();
  });

  it('asks the server to trust this browser when ticked — authenticator code', async () => {
    mockVerifyTotp.mockResolvedValue(OK);
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    await user.click(screen.getByTestId('two-factor-trust-device'));
    submitTotp();

    await waitFor(() =>
      expect(mockVerifyTotp).toHaveBeenCalledWith({ code: '123456', trustDevice: true })
    );
  });

  it('asks the server to trust this browser when ticked — email code', async () => {
    window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['otp']));
    mockVerifyOtp.mockResolvedValue(OK);
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    await user.click(screen.getByTestId('two-factor-trust-device'));
    fireEvent.change(screen.getByTestId('two-factor-otp-code'), { target: { value: '654321' } });
    fireEvent.submit(screen.getByTestId('two-factor-card').querySelector('form')!);

    await waitFor(() =>
      expect(mockVerifyOtp).toHaveBeenCalledWith({ code: '654321', trustDevice: true })
    );
  });

  it('carries the choice over to the backup-code form', async () => {
    mockVerifyBackupCode.mockResolvedValue(OK);
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    await user.click(screen.getByTestId('two-factor-trust-device'));
    const field = await openBackupForm(user);
    expect(screen.getByTestId('two-factor-trust-device')).toBeChecked();

    fireEvent.change(field, { target: { value: BACKUP_CODE } });
    await user.click(screen.getByTestId('two-factor-backup-submit'));
    await waitFor(() =>
      expect(mockVerifyBackupCode).toHaveBeenCalledWith({ code: BACKUP_CODE, trustDevice: true })
    );
  });
});

describe('lockout', () => {
  const LOCKED = {
    data: null,
    error: {
      code: 'ACCOUNT_TEMPORARILY_LOCKED',
      message: 'Too many failed verification attempts. Your account is temporarily locked.',
      status: 429,
    },
  };

  it('says the factor is locked and for how long, and closes the form', async () => {
    mockVerifyTotp.mockResolvedValue(LOCKED);
    render(<TwoFactorClient callbackUrl="/ade" />);

    submitTotp();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many incorrect codes. Two-factor sign-in is locked for 15 minutes. Try again later, or ask an admin for help.'
    );
    expect(screen.getByTestId('two-factor-totp-code')).toBeDisabled();
    expect(screen.getByTestId('two-factor-submit')).toBeDisabled();
    expect(screen.getByTestId('two-factor-trust-device')).toBeDisabled();
    // A backup code is refused by the same lock, so the recovery path is not offered.
    expect(screen.queryByTestId('two-factor-toggle-backup')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Back to sign in/ })).toBeInTheDocument();
    expect(mockBrowserNavigate).not.toHaveBeenCalled();
  });

  it('applies to a backup code too', async () => {
    mockVerifyBackupCode.mockResolvedValue(LOCKED);
    const user = userEvent.setup();
    render(<TwoFactorClient callbackUrl="/ade" />);

    const field = await openBackupForm(user);
    fireEvent.change(field, { target: { value: BACKUP_CODE } });
    await user.click(screen.getByTestId('two-factor-backup-submit'));

    expect(await screen.findByRole('alert')).toHaveTextContent('locked for 15 minutes');
    expect(field).toBeDisabled();
    expect(screen.getByTestId('two-factor-backup-submit')).toBeDisabled();
  });

  it.each([
    ['TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE', 'Too many incorrect codes for this sign-in.'],
    ['INVALID_TWO_FACTOR_COOKIE', 'This sign-in step has expired.'],
  ])('closes the form when the challenge is spent (%s)', async (code, sentence) => {
    mockVerifyTotp.mockResolvedValue({ data: null, error: { code, message: 'server', status: 401 } });
    render(<TwoFactorClient callbackUrl="/ade" />);

    submitTotp();

    expect(await screen.findByRole('alert')).toHaveTextContent(sentence);
    expect(screen.getByTestId('two-factor-totp-code')).toBeDisabled();
  });

  it('keeps the form open after an ordinary wrong code', async () => {
    mockVerifyTotp.mockResolvedValue({
      data: null,
      error: { code: 'INVALID_CODE', message: 'Invalid code', status: 401 },
    });
    render(<TwoFactorClient callbackUrl="/ade" />);

    submitTotp();

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid code');
    expect(screen.getByTestId('two-factor-totp-code')).toBeEnabled();
    expect(screen.getByTestId('two-factor-toggle-backup')).toBeInTheDocument();
  });
});

describe('methods named by the server (provider sign-in, TFA-1.1 #5655)', () => {
  it('offers the methods from the URL when nothing was stored', () => {
    render(<TwoFactorClient callbackUrl="/ade" methods={['totp', 'otp']} />);
    expect(screen.getByTestId('two-factor-method-switcher')).toBeInTheDocument();
  });

  it('draws the email form alone when that is the only method', () => {
    render(<TwoFactorClient callbackUrl="/ade" methods={['otp']} />);
    expect(screen.getByTestId('two-factor-send-otp')).toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-totp-code')).not.toBeInTheDocument();
  });

  it("prefers the server's methods over ones an earlier, abandoned sign-in left behind", () => {
    window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['totp', 'otp']));
    render(<TwoFactorClient callbackUrl="/ade" methods={['totp']} />);
    expect(screen.queryByTestId('two-factor-method-switcher')).not.toBeInTheDocument();
    expect(screen.getByTestId('two-factor-totp-code')).toBeInTheDocument();
  });

  it('falls back to the stored methods when the URL names none', () => {
    window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['totp', 'otp']));
    render(<TwoFactorClient callbackUrl="/ade" methods={[]} />);
    expect(screen.getByTestId('two-factor-method-switcher')).toBeInTheDocument();
  });

  it('verifies a code after a provider sign-in and leaves for the destination', async () => {
    mockVerifyTotp.mockResolvedValue(OK);
    render(<TwoFactorClient callbackUrl="/ade/dashboard/projects" methods={['totp']} />);

    submitTotp();

    await waitFor(() => expect(mockBrowserNavigate).toHaveBeenCalledWith('/ade/dashboard/projects'));
  });
});

describe('accessibility', () => {
  it('has no axe violations on the backup-code form', async () => {
    const user = userEvent.setup();
    const { container } = render(<TwoFactorClient callbackUrl="/ade" />);
    await openBackupForm(user);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations on the verification form with the trust box', async () => {
    const { container } = render(<TwoFactorClient callbackUrl="/ade" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
