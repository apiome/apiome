/**
 * The text-message (SMS) two-factor box on Profile → Security (OLO-9.51 #5071).
 *
 * Pinned: a number is added only through the texted code, in `updatePhoneNumber` mode; SMS can
 * only be chosen once a number is verified, and choosing it asks for the password; a refusal is
 * shown in words; removing the number reloads the status.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  SmsTwoFactorSettings,
  SMS_REFUSAL_COPY,
} from '@/app/components/ade/account/SmsTwoFactorSettings';
import type { TwoFactorReauth } from '@/app/components/ade/account/useTwoFactorReauth';
import type { SmsTwoFactorStatus } from '@lib/auth/two-factor-sms-actions';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const mockSendOtp = jest.fn();
const mockVerify = jest.fn();
const mockSetChannel = jest.fn();
const mockRemove = jest.fn();

jest.mock('@lib/auth/auth-client', () => ({
  authClient: {
    phoneNumber: {
      sendOtp: (...args: unknown[]) => mockSendOtp(...args),
      verify: (...args: unknown[]) => mockVerify(...args),
    },
  },
}));

jest.mock('@lib/auth/two-factor-sms-actions', () => ({
  setTwoFactorOtpChannel: (...args: unknown[]) => mockSetChannel(...args),
  removePhoneNumber: (...args: unknown[]) => mockRemove(...args),
}));

const PASSWORD_REAUTH: TwoFactorReauth = {
  reauth: null,
  passwordless: false,
  needsReauth: false,
  markStale: jest.fn(),
};

const NO_PHONE: SmsTwoFactorStatus = {
  smsAvailable: true,
  emailAvailable: true,
  phoneNumber: null,
  channel: 'email',
};
const VERIFIED: SmsTwoFactorStatus = { ...NO_PHONE, phoneNumber: '•••• 0123' };
const USING_SMS: SmsTwoFactorStatus = { ...VERIFIED, channel: 'sms' };

/** Render the box with a fresh `onChanged` spy. */
function renderBox(status: SmsTwoFactorStatus, reauth: TwoFactorReauth = PASSWORD_REAUTH) {
  const onChanged = jest.fn(async () => undefined);
  render(
    <SmsTwoFactorSettings
      status={status}
      onChanged={onChanged}
      reauth={reauth}
      onReauth={jest.fn()}
    />,
  );
  return { onChanged };
}

describe('SmsTwoFactorSettings', () => {
  beforeEach(() => jest.clearAllMocks());

  it('asks for a number first and does not offer SMS without one', () => {
    renderBox(NO_PHONE);
    expect(screen.getByTestId('two-factor-sms-status')).toHaveTextContent(
      'Add and verify a phone number first.',
    );
    expect(screen.queryByTestId('two-factor-sms-use')).not.toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-sms-remove')).not.toBeInTheDocument();
  });

  it('adds a number through the texted code, attached to this account', async () => {
    mockSendOtp.mockResolvedValue({ data: { message: 'code sent' }, error: null });
    mockVerify.mockResolvedValue({ data: { status: true }, error: null });
    const { onChanged } = renderBox(NO_PHONE);

    fireEvent.click(screen.getByTestId('two-factor-sms-add'));
    fireEvent.change(screen.getByTestId('two-factor-sms-phone'), {
      target: { value: '+1 (415) 555-0123' },
    });
    fireEvent.click(screen.getByTestId('two-factor-sms-send'));
    await waitFor(() => expect(mockSendOtp).toHaveBeenCalledWith({ phoneNumber: '+14155550123' }));

    fireEvent.change(await screen.findByTestId('two-factor-sms-code'), {
      target: { value: '12a3456' },
    });
    expect(screen.getByTestId('two-factor-sms-code')).toHaveValue('123456');
    fireEvent.click(screen.getByTestId('two-factor-sms-verify'));

    await waitFor(() =>
      expect(mockVerify).toHaveBeenCalledWith({
        phoneNumber: '+14155550123',
        code: '123456',
        updatePhoneNumber: true,
      }),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('refuses a number without a country code before sending anything', async () => {
    renderBox(NO_PHONE);
    fireEvent.click(screen.getByTestId('two-factor-sms-add'));
    fireEvent.change(screen.getByTestId('two-factor-sms-phone'), {
      target: { value: '415 555 0123' },
    });
    fireEvent.click(screen.getByTestId('two-factor-sms-send'));
    expect(await screen.findByText(/country code, like \+1 415 555 0123/)).toBeInTheDocument();
    expect(mockSendOtp).not.toHaveBeenCalled();
  });

  it('shows the server sentence when the code is wrong', async () => {
    mockSendOtp.mockResolvedValue({ data: {}, error: null });
    mockVerify.mockResolvedValue({ data: null, error: { message: 'Invalid OTP' } });
    renderBox(NO_PHONE);
    fireEvent.click(screen.getByTestId('two-factor-sms-add'));
    fireEvent.change(screen.getByTestId('two-factor-sms-phone'), {
      target: { value: '+14155550123' },
    });
    fireEvent.click(screen.getByTestId('two-factor-sms-send'));
    fireEvent.change(await screen.findByTestId('two-factor-sms-code'), {
      target: { value: '000000' },
    });
    fireEvent.click(screen.getByTestId('two-factor-sms-verify'));
    expect(await screen.findByText('Invalid OTP')).toBeInTheDocument();
  });

  it('switches codes to text messages after the password', async () => {
    mockSetChannel.mockResolvedValue({ ok: true });
    const { onChanged } = renderBox(VERIFIED);
    expect(screen.getByTestId('two-factor-sms-status')).toHaveTextContent('•••• 0123 is verified');

    fireEvent.click(screen.getByTestId('two-factor-sms-use'));
    fireEvent.click(screen.getByTestId('two-factor-sms-channel-confirm'));
    expect(await screen.findByText(/Enter your current password/)).toBeInTheDocument();
    expect(mockSetChannel).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId('two-factor-sms-password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByTestId('two-factor-sms-channel-confirm'));
    await waitFor(() =>
      expect(mockSetChannel).toHaveBeenCalledWith({ channel: 'sms', password: 'pw' }),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('shows the guidance when the server says the number is not verified', async () => {
    mockSetChannel.mockResolvedValue({ ok: false, error: 'PHONE_NUMBER_NOT_VERIFIED' });
    renderBox(VERIFIED);
    fireEvent.click(screen.getByTestId('two-factor-sms-use'));
    fireEvent.change(screen.getByTestId('two-factor-sms-password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByTestId('two-factor-sms-channel-confirm'));
    expect(await screen.findByText(SMS_REFUSAL_COPY.PHONE_NUMBER_NOT_VERIFIED)).toBeInTheDocument();
  });

  it('marks a passwordless session stale when the server asks for a fresh sign-in', async () => {
    mockSetChannel.mockResolvedValue({ ok: false, error: 'REAUTH_REQUIRED' });
    const reauth: TwoFactorReauth = {
      reauth: { hasPassword: false, fresh: true, providers: [] },
      passwordless: true,
      needsReauth: false,
      markStale: jest.fn(),
    };
    renderBox(VERIFIED, reauth);
    fireEvent.click(screen.getByTestId('two-factor-sms-use'));
    expect(screen.queryByTestId('two-factor-sms-password')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('two-factor-sms-channel-confirm'));
    await waitFor(() =>
      expect(mockSetChannel).toHaveBeenCalledWith({ channel: 'sms', password: undefined }),
    );
    await waitFor(() => expect(reauth.markStale).toHaveBeenCalled());
  });

  it('offers email again, and removal, while codes go by text', async () => {
    mockRemove.mockResolvedValue({ ok: true });
    const { onChanged } = renderBox(USING_SMS);
    expect(screen.getByTestId('two-factor-sms-status')).toHaveTextContent(
      'Sign-in codes are texted to •••• 0123.',
    );
    expect(screen.getByTestId('two-factor-sms-use-email')).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-sms-add')).toHaveTextContent('Change number');

    fireEvent.click(screen.getByTestId('two-factor-sms-remove'));
    await waitFor(() => expect(mockRemove).toHaveBeenCalled());
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  /**
   * The docs site's Profile page shows the add-number dialog from this dump:
   * `A11Y_FIXTURE_DUMP=1 npx jest tests/sms-two-factor-settings.test.tsx -t "docs fixture"`.
   */
  it('renders the docs fixture of the add-number dialog at the code step', async () => {
    mockSendOtp.mockResolvedValue({ data: {}, error: null });
    renderBox(NO_PHONE);
    fireEvent.click(screen.getByTestId('two-factor-sms-add'));
    fireEvent.change(screen.getByTestId('two-factor-sms-phone'), {
      target: { value: '+1 415 555 0123' },
    });
    fireEvent.click(screen.getByTestId('two-factor-sms-send'));
    fireEvent.change(await screen.findByTestId('two-factor-sms-code'), { target: { value: '482913' } });
    writeA11yFixture('profile-2fa-sms-add', liveMarkup(screen.getByRole('dialog')));
  });
});
