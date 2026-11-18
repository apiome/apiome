/**
 * Login 2FA step UI tests (OLO-9.13 #5014 + OLO-9.50 #5070 + OLO-9.51 #5071).
 *
 * The flow contract, which HIVE-4.2 (#5296) re-skinned without moving: both methods, the
 * switcher, the stored callback, and every error string. `two-factor-hive-redesign.test.tsx`
 * pins what the screen is now *made of*.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TwoFactorClient from '@/app/login/2fa/TwoFactorClient';
import {
  TWO_FACTOR_CALLBACK_STORAGE_KEY,
  TWO_FACTOR_METHODS_STORAGE_KEY,
} from '@lib/auth/two-factor-callback';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const mockVerifyTotp = jest.fn();
const mockVerifyOtp = jest.fn();
const mockSendOtp = jest.fn();
const mockBrowserNavigate = jest.fn();

jest.mock('@lib/auth/auth-client', () => ({
  authClient: {
    twoFactor: {
      verifyTotp: (...args: unknown[]) => mockVerifyTotp(...args),
      verifyOtp: (...args: unknown[]) => mockVerifyOtp(...args),
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

describe('TwoFactorClient', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.sessionStorage.clear();
  });

  it('rejects a non-6-digit code without calling the API', async () => {
    render(<TwoFactorClient callbackUrl="/ade" />);

    fireEvent.change(screen.getByLabelText(/authentication code/i), { target: { value: '12' } });
    fireEvent.submit(screen.getByTestId('two-factor-card').querySelector('form')!);

    expect(await screen.findByRole('alert')).toHaveTextContent(/6-digit/i);
    expect(mockVerifyTotp).not.toHaveBeenCalled();
  });

  it('verifies a valid TOTP code and navigates to the stored callback', async () => {
    window.sessionStorage.setItem(TWO_FACTOR_CALLBACK_STORAGE_KEY, '/ade/dashboard');
    mockVerifyTotp.mockResolvedValue({ data: { token: 'ok' }, error: null });

    render(<TwoFactorClient callbackUrl="/ade" />);

    fireEvent.change(screen.getByLabelText(/authentication code/i), {
      target: { value: '123456' },
    });
    fireEvent.click(screen.getByTestId('two-factor-submit'));

    await waitFor(() => {
      expect(mockVerifyTotp).toHaveBeenCalledWith({ code: '123456', trustDevice: false });
      expect(mockBrowserNavigate).toHaveBeenCalledWith('/ade/dashboard');
    });
  });

  it('shows an error when verifyTotp fails', async () => {
    mockVerifyTotp.mockResolvedValue({
      data: null,
      error: { message: 'Invalid code' },
    });

    render(<TwoFactorClient callbackUrl="/ade" />);

    fireEvent.change(screen.getByLabelText(/authentication code/i), {
      target: { value: '000000' },
    });
    fireEvent.click(screen.getByTestId('two-factor-submit'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid code');
  });

  it('sends and verifies email OTP when methods include otp only', async () => {
    window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['otp']));
    window.sessionStorage.setItem(TWO_FACTOR_CALLBACK_STORAGE_KEY, '/ade');
    mockSendOtp.mockResolvedValue({ data: { status: true }, error: null });
    mockVerifyOtp.mockResolvedValue({ data: { token: 'ok' }, error: null });

    render(<TwoFactorClient callbackUrl="/ade" />);

    expect(screen.getByTestId('two-factor-send-otp')).toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-method-switcher')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('two-factor-send-otp'));
    await waitFor(() => expect(mockSendOtp).toHaveBeenCalled());

    fireEvent.change(screen.getByTestId('two-factor-otp-code'), { target: { value: '654321' } });
    fireEvent.click(screen.getByTestId('two-factor-otp-submit'));

    await waitFor(() => {
      expect(mockVerifyOtp).toHaveBeenCalledWith({ code: '654321', trustDevice: false });
      expect(mockBrowserNavigate).toHaveBeenCalledWith('/ade');
    });
  });

  it('lets the user switch between authenticator and email when both methods are offered', async () => {
    window.sessionStorage.setItem(
      TWO_FACTOR_METHODS_STORAGE_KEY,
      JSON.stringify(['totp', 'otp'])
    );
    const user = userEvent.setup();

    render(<TwoFactorClient callbackUrl="/ade" />);

    expect(screen.getByTestId('two-factor-method-switcher')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-submit')).toBeInTheDocument();

    await user.click(screen.getByTestId('two-factor-method-otp'));
    expect(screen.getByTestId('two-factor-send-otp')).toBeInTheDocument();

    await user.click(screen.getByTestId('two-factor-method-totp'));
    expect(screen.getByTestId('two-factor-submit')).toBeInTheDocument();
  });

  it('clears a half-typed code and its error when the method changes', async () => {
    window.sessionStorage.setItem(
      TWO_FACTOR_METHODS_STORAGE_KEY,
      JSON.stringify(['totp', 'otp'])
    );
    const user = userEvent.setup();

    render(<TwoFactorClient callbackUrl="/ade" />);

    // An authenticator code is not an email code, and the sentence about one would be
    // read as being about the other — so both go with the method that owned them.
    fireEvent.change(screen.getByLabelText(/authentication code/i), { target: { value: '123' } });
    fireEvent.submit(screen.getByTestId('two-factor-card').querySelector('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Enter the 6-digit code from your authenticator app.'
    );

    await user.click(screen.getByTestId('two-factor-method-otp'));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByTestId('two-factor-otp-code')).toHaveValue('');
    expect(mockVerifyTotp).not.toHaveBeenCalled();
  });

  describe('SMS delivery (OLO-9.51 #5071)', () => {
    const SMS = { channel: 'sms' as const, destination: '•••• 0123', available: true };

    it('names the masked number and texts the code through the same OTP method', async () => {
      window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['otp']));
      mockSendOtp.mockResolvedValue({ data: { status: true }, error: null });
      mockVerifyOtp.mockResolvedValue({ data: { token: 'ok' }, error: null });

      render(<TwoFactorClient callbackUrl="/ade" otpDelivery={SMS} />);

      expect(screen.getByRole('heading', { name: 'Check your phone' })).toBeInTheDocument();
      expect(screen.getByText('We will text a 6-digit code to •••• 0123.')).toBeInTheDocument();
      expect(screen.getByTestId('two-factor-send-otp')).toHaveTextContent('Send text code');

      fireEvent.click(screen.getByTestId('two-factor-send-otp'));
      expect(await screen.findByTestId('two-factor-otp-sent')).toHaveTextContent(
        'Text code sent. Check your phone.'
      );
      expect(screen.getByText('Enter the 6-digit code we texted to •••• 0123.')).toBeInTheDocument();
      expect(screen.getByTestId('two-factor-send-otp')).toHaveTextContent('Resend text code');

      fireEvent.change(screen.getByLabelText('Text message code'), { target: { value: '112233' } });
      fireEvent.click(screen.getByTestId('two-factor-otp-submit'));
      await waitFor(() => {
        expect(mockVerifyOtp).toHaveBeenCalledWith({ code: '112233', trustDevice: false });
        expect(mockBrowserNavigate).toHaveBeenCalledWith('/ade');
      });
    });

    /**
     * The docs site's Sign in page shows the texted-code step from this dump:
     * `A11Y_FIXTURE_DUMP=1 npx jest tests/login-two-factor.test.tsx -t "docs fixture"`.
     */
    it('renders the docs fixture of the Text message tab after a send', async () => {
      mockSendOtp.mockResolvedValue({ data: { status: true }, error: null });
      const user = userEvent.setup();
      const { container } = render(
        <TwoFactorClient callbackUrl="/ade" methods={['totp', 'otp']} otpDelivery={SMS} />
      );
      await user.click(screen.getByTestId('two-factor-method-otp'));
      fireEvent.click(screen.getByTestId('two-factor-send-otp'));
      await screen.findByTestId('two-factor-otp-sent');
      fireEvent.change(screen.getByLabelText('Text message code'), { target: { value: '482913' } });
      writeA11yFixture('sign-in-2fa-sms', liveMarkup(container.firstElementChild as Element));
    });

    it('labels the switcher tab "Text message"', () => {
      render(<TwoFactorClient callbackUrl="/ade" methods={['totp', 'otp']} otpDelivery={SMS} />);
      expect(screen.getByTestId('two-factor-method-otp')).toHaveTextContent('Text message');
    });

    it('shows the SMS fallback sentence when the send fails without a message', async () => {
      window.sessionStorage.setItem(TWO_FACTOR_METHODS_STORAGE_KEY, JSON.stringify(['otp']));
      mockSendOtp.mockResolvedValue({ data: null, error: {} });

      render(<TwoFactorClient callbackUrl="/ade" otpDelivery={SMS} />);
      fireEvent.click(screen.getByTestId('two-factor-send-otp'));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Could not send the text code. Try again.'
      );
    });

    it('keeps the email wording when the delivery is unknown or email', () => {
      render(
        <TwoFactorClient
          callbackUrl="/ade"
          methods={['otp']}
          otpDelivery={{ channel: 'email', destination: '', available: true }}
        />
      );
      expect(screen.getByRole('heading', { name: 'Check your email' })).toBeInTheDocument();
      expect(screen.getByTestId('two-factor-send-otp')).toHaveTextContent('Send email code');
    });

    it('hides the code method when this user\'s channel cannot deliver', () => {
      render(
        <TwoFactorClient
          callbackUrl="/ade"
          methods={['totp', 'otp']}
          otpDelivery={{ channel: 'email', destination: '', available: false }}
        />
      );
      expect(screen.queryByTestId('two-factor-method-switcher')).not.toBeInTheDocument();
      expect(screen.queryByTestId('two-factor-send-otp')).not.toBeInTheDocument();
      expect(screen.getByTestId('two-factor-submit')).toBeInTheDocument();
    });
  });
});
