/**
 * Enforcing a workspace's two-factor requirement — TFA-1.3 (#5657).
 *
 * - `TwoFactorRequirementGuard` swaps every `/ade` route for the blocking screen once the earliest
 *   deadline has passed, and fails open on a lookup error;
 * - `TwoFactorRequiredScreen` names the workspaces, runs the shared enrolment, and refreshes the
 *   route once enrolled — its only other way out is signing out;
 * - `TwoFactorGraceNotice` reminds a member inside their grace period, until dismissed for the
 *   session or enrolled;
 * - `getMyTwoFactorRequirement` answers for the session's own account and fails open.
 */

import React from 'react';
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockGetAuthSession = jest.fn();
jest.mock('@lib/auth/server-session', () => ({ getAuthSession: () => mockGetAuthSession() }));

const mockReadRequirement = jest.fn();
jest.mock('@lib/auth/two-factor-requirement', () => ({
  readTwoFactorRequirement: (...args: unknown[]) => mockReadRequirement(...args),
}));

const mockUseAuthSession = jest.fn();
const mockUpdate = jest.fn(async () => null);
jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => mockUseAuthSession(),
  signIn: jest.fn(),
}));

const mockSignOutEverywhere = jest.fn();
jest.mock('@lib/auth/sign-out-client', () => ({
  signOutEverywhere: (...args: unknown[]) => mockSignOutEverywhere(...args),
}));

const mockRefresh = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), refresh: mockRefresh }) }));

jest.mock('@lib/auth/two-factor-profile-actions', () => ({
  getTwoFactorReauthStatus: jest.fn(async () => ({ hasPassword: true, fresh: true, providers: [] })),
  dismissTwoFactorResetNotice: jest.fn(async () => undefined),
}));

const mockEnable = jest.fn();
const mockVerifyTotp = jest.fn();
jest.mock('@lib/auth/auth-client', () => ({
  authClient: {
    twoFactor: {
      enable: (...args: unknown[]) => mockEnable(...args),
      verifyTotp: (...args: unknown[]) => mockVerifyTotp(...args),
    },
  },
}));
jest.mock('react-qr-code', () => ({
  __esModule: true,
  default: ({ value }: { value: string }) => <div data-testid="qr-code" data-value={value} />,
}));

const mockGetMyRequirement = jest.fn();
jest.mock('@lib/auth/two-factor-requirement-actions', () => ({
  getMyTwoFactorRequirement: () => mockGetMyRequirement(),
}));

import TwoFactorRequirementGuard from '@/app/components/auth/TwoFactorRequirementGuard';
import { TwoFactorRequiredScreen } from '@/app/components/auth/TwoFactorRequiredScreen';
import {
  GRACE_NOTICE_DISMISSED_KEY,
  TwoFactorGraceNotice,
  graceRemainingPhrase,
} from '@/app/components/auth/TwoFactorGraceNotice';
import { NO_TWO_FACTOR_REQUIREMENT } from '@lib/two-factor-policy';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const ACME = { tenantName: 'Acme Corp', dueAt: '2026-10-20T12:00:00Z' };
const GLOBEX = { tenantName: 'Globex', dueAt: '2026-10-28T12:00:00Z' };

beforeEach(() => {
  jest.clearAllMocks();
  window.sessionStorage.clear();
  mockUpdate.mockResolvedValue(null);
  mockUseAuthSession.mockReturnValue({
    data: { user: { user_id: 'u-1', email: 'ada@acme.io', twoFactorEnabled: false } },
    update: mockUpdate,
  });
});

// =========================================================================================
// The guard
// =========================================================================================

describe('TwoFactorRequirementGuard', () => {
  /** Await the async server component and render what it returned. */
  const renderGuard = async () => render(await TwoFactorRequirementGuard({ children: <p>The route</p> }));

  it('renders the route without a session, without asking the database', async () => {
    mockGetAuthSession.mockResolvedValue(null);
    await renderGuard();
    expect(screen.getByText('The route')).toBeInTheDocument();
    expect(mockReadRequirement).not.toHaveBeenCalled();
  });

  it('renders the route while nothing is owed or the grace period is running', async () => {
    mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u-1', email: 'ada@acme.io' } });
    mockReadRequirement.mockResolvedValue(NO_TWO_FACTOR_REQUIREMENT);
    await renderGuard();
    expect(screen.getByText('The route')).toBeInTheDocument();

    mockReadRequirement.mockResolvedValue({ tenants: [GLOBEX], dueAt: GLOBEX.dueAt, overdue: false });
    await renderGuard();
    expect(screen.getAllByText('The route')).toHaveLength(2);
    expect(mockReadRequirement).toHaveBeenCalledWith('u-1');
  });

  it('replaces the route with the blocking screen once the deadline has passed', async () => {
    mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u-1', email: 'ada@acme.io' } });
    mockReadRequirement.mockResolvedValue({ tenants: [ACME], dueAt: ACME.dueAt, overdue: true });
    await renderGuard();
    expect(screen.queryByText('The route')).not.toBeInTheDocument();
    expect(screen.getByTestId('two-factor-required-screen')).toBeInTheDocument();
  });

  it('fails open when the lookup fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u-1' } });
    mockReadRequirement.mockRejectedValue(new Error('db down'));
    await renderGuard();
    expect(screen.getByText('The route')).toBeInTheDocument();
    consoleError.mockRestore();
  });
});

// =========================================================================================
// The blocking screen
// =========================================================================================

describe('TwoFactorRequiredScreen', () => {
  it('names the workspace and the deadline, with only two ways on', async () => {
    const { container } = render(<TwoFactorRequiredScreen tenants={[ACME]} email="ada@acme.io" />);

    expect(screen.getByRole('heading', { name: 'Set up two-factor to continue' })).toBeInTheDocument();
    expect(screen.getByTestId('two-factor-required-reason')).toHaveTextContent(
      /^Acme Corp requires two-factor authentication for every member, and your grace period ended on /
    );
    expect(screen.getByTestId('two-factor-required-signed-in-as')).toHaveTextContent('ada@acme.io');
    const card = screen.getByTestId('two-factor-required-screen');
    expect(within(card).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Sign out',
      'Set up two-factor',
    ]);
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('two-factor-required', container.innerHTML);
  });

  it('says "require" for more than one workspace', () => {
    render(<TwoFactorRequiredScreen tenants={[ACME, GLOBEX]} email={null} />);
    expect(screen.getByTestId('two-factor-required-reason')).toHaveTextContent(
      /^Acme Corp and Globex require two-factor/
    );
  });

  it('signs out', () => {
    render(<TwoFactorRequiredScreen tenants={[ACME]} email={null} />);
    fireEvent.click(screen.getByTestId('two-factor-required-sign-out'));
    expect(mockSignOutEverywhere).toHaveBeenCalledWith('/login');
  });

  it('runs the shared enrolment and refreshes the route once enrolled', async () => {
    mockEnable.mockResolvedValue({ data: { totpURI: 'otpauth://totp/apiome:ada?secret=ABC', backupCodes: ['a-b'] } });
    mockVerifyTotp.mockResolvedValue({ data: { status: true } });
    render(<TwoFactorRequiredScreen tenants={[ACME]} email={null} />);

    fireEvent.click(screen.getByTestId('two-factor-required-enable'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Current password'), { target: { value: 'pw' } });
    fireEvent.click(within(dialog).getByTestId('two-factor-enroll-continue'));
    fireEvent.change(await within(dialog).findByTestId('two-factor-enroll-code'), { target: { value: '123456' } });
    fireEvent.click(within(dialog).getByTestId('two-factor-enroll-verify'));
    await within(dialog).findByText(/regenerate a new set later from your profile/i);
    expect(mockRefresh).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByTestId('two-factor-enroll-done'));
    await waitFor(() => expect(mockRefresh).toHaveBeenCalledTimes(1));
  });

  it('does not refresh when the dialog is cancelled', async () => {
    render(<TwoFactorRequiredScreen tenants={[ACME]} email={null} />);
    fireEvent.click(screen.getByTestId('two-factor-required-enable'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mockRefresh).not.toHaveBeenCalled();
  });
});

// =========================================================================================
// The grace notice
// =========================================================================================

describe('TwoFactorGraceNotice', () => {
  const inGrace = (dueAt: string) => ({ tenants: [{ tenantName: 'Acme Corp', dueAt }], dueAt, overdue: false });
  const future = (days: number) => new Date(Date.now() + days * 86_400_000 - 60_000).toISOString();

  it('phrases the time left', () => {
    const now = new Date('2026-10-23T12:00:00Z');
    expect(graceRemainingPhrase('2026-10-23T18:00:00Z', now)).toBe('in 1 day');
    expect(graceRemainingPhrase('2026-10-26T12:00:00Z', now)).toBe('in 3 days');
    expect(graceRemainingPhrase('2026-10-20T12:00:00Z', now)).toBe('today');
  });

  it('reminds a member inside their grace period, linking to the profile', async () => {
    mockGetMyRequirement.mockResolvedValue(inGrace(future(3)));
    render(<TwoFactorGraceNotice />);

    const notice = await screen.findByTestId('two-factor-grace-notice');
    expect(notice).toHaveAttribute('role', 'status');
    expect(notice).toHaveTextContent('Set up two-factor in 3 days');
    expect(notice).toHaveTextContent('Acme Corp requires two-factor authentication.');
    expect(within(notice).getByRole('link', { name: 'Set up two-factor' })).toHaveAttribute(
      'href',
      '/ade/dashboard/profile'
    );
  });

  it('hides for the rest of the session on Dismiss', async () => {
    mockGetMyRequirement.mockResolvedValue(inGrace(future(3)));
    const { unmount } = render(<TwoFactorGraceNotice />);
    fireEvent.click(await screen.findByTestId('two-factor-grace-notice-dismiss'));
    expect(screen.queryByTestId('two-factor-grace-notice')).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(GRACE_NOTICE_DISMISSED_KEY)).toBe('1');

    unmount();
    render(<TwoFactorGraceNotice />);
    await waitFor(() => expect(mockGetMyRequirement).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('two-factor-grace-notice')).not.toBeInTheDocument();
  });

  it('says nothing when nothing is owed, when overdue (the guard blocks), or once enrolled', async () => {
    mockGetMyRequirement.mockResolvedValue(NO_TWO_FACTOR_REQUIREMENT);
    const first = render(<TwoFactorGraceNotice />);
    await waitFor(() => expect(mockGetMyRequirement).toHaveBeenCalled());
    expect(first.container).toBeEmptyDOMElement();
    first.unmount();

    mockGetMyRequirement.mockResolvedValue({ ...inGrace(ACME.dueAt), overdue: true });
    const second = render(<TwoFactorGraceNotice />);
    await waitFor(() => expect(mockGetMyRequirement).toHaveBeenCalledTimes(2));
    expect(second.container).toBeEmptyDOMElement();
    second.unmount();

    mockUseAuthSession.mockReturnValue({ data: { user: { user_id: 'u-1', twoFactorEnabled: true } }, update: mockUpdate });
    const third = render(<TwoFactorGraceNotice />);
    expect(third.container).toBeEmptyDOMElement();
    expect(mockGetMyRequirement).toHaveBeenCalledTimes(2);
  });
});
