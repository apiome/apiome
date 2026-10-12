/**
 * "Your two-factor authentication was reset" — the prompt to enrol again (TFA-1.2, #5656).
 *
 * Shown on signed-in pages after an administrator's reset, until the user sets two-factor up again
 * or dismisses it. Almost always it renders nothing.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TwoFactorResetNotice } from '@/app/components/auth/TwoFactorResetNotice';

const mockUseAuthSession = jest.fn();
const mockGetNotice = jest.fn();
const mockDismiss = jest.fn();

jest.mock('@lib/auth/session-client', () => ({ useAuthSession: () => mockUseAuthSession() }));
jest.mock('@lib/auth/two-factor-profile-actions', () => ({
  getTwoFactorResetNotice: (...args: unknown[]) => mockGetNotice(...args),
  dismissTwoFactorResetNotice: (...args: unknown[]) => mockDismiss(...args),
}));

/** Set who is signed in. */
const signedIn = (user: { twoFactorEnabled?: boolean } | null) =>
  mockUseAuthSession.mockReturnValue({ data: user ? { user: { user_id: 'u1', ...user } } : null });

beforeEach(() => {
  jest.clearAllMocks();
  signedIn({ twoFactorEnabled: false });
  mockGetNotice.mockResolvedValue({ resetAt: '2026-10-12T09:00:00.000Z' });
  mockDismiss.mockResolvedValue({ ok: true });
});

describe('TwoFactorResetNotice', () => {
  it('tells a user whose two-factor was reset to set it up again', async () => {
    render(<TwoFactorResetNotice />);

    const notice = await screen.findByTestId('two-factor-reset-notice');
    expect(notice).toHaveAttribute('role', 'status');
    expect(notice).toHaveTextContent('Your two-factor authentication was reset');
    expect(notice).toHaveTextContent('An administrator reset it, so you now sign in without a code.');
    expect(screen.getByRole('link', { name: 'Set up two-factor' })).toHaveAttribute(
      'href',
      '/ade/dashboard/profile'
    );
  });

  it('renders nothing when there is no outstanding reset', async () => {
    mockGetNotice.mockResolvedValue({ resetAt: null });
    const { container } = render(<TwoFactorResetNotice />);
    await waitFor(() => expect(mockGetNotice).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('asks nothing and shows nothing when nobody is signed in', () => {
    signedIn(null);
    const { container } = render(<TwoFactorResetNotice />);
    expect(mockGetNotice).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it('asks nothing for a user who has two-factor on', () => {
    signedIn({ twoFactorEnabled: true });
    const { container } = render(<TwoFactorResetNotice />);
    expect(mockGetNotice).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it.each(['two-factor-reset-notice-dismiss', 'close'])('goes away, for good, when dismissed (%s)', async (control) => {
    render(<TwoFactorResetNotice />);
    await screen.findByTestId('two-factor-reset-notice');

    fireEvent.click(
      control === 'close'
        ? screen.getByRole('button', { name: 'Dismiss the two-factor reset notice' })
        : screen.getByTestId(control)
    );

    expect(screen.queryByTestId('two-factor-reset-notice')).not.toBeInTheDocument();
    expect(mockDismiss).toHaveBeenCalledTimes(1);
  });

  it('hides itself once the user enrols again', async () => {
    const { rerender } = render(<TwoFactorResetNotice />);
    await screen.findByTestId('two-factor-reset-notice');

    signedIn({ twoFactorEnabled: true });
    rerender(<TwoFactorResetNotice />);

    expect(screen.queryByTestId('two-factor-reset-notice')).not.toBeInTheDocument();
  });

  it('stays quiet when the status cannot be read', async () => {
    mockGetNotice.mockRejectedValue(new Error('offline'));
    const { container } = render(<TwoFactorResetNotice />);
    await waitFor(() => expect(mockGetNotice).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
