/**
 * First-tenant onboarding route guard tests (OLO-3.3, #4201).
 *
 * The guard implements the zero-tenant half of the post-login routing rules on
 * the /ade shell: authenticated users with no tenant memberships see the
 * onboarding prompt in place of any route content (so deep links cannot route
 * around the wizard), while members, signed-out visitors, and membership-store
 * failures all render the route unchanged. Also covers the prompt's two
 * actions: re-checking memberships and signing out.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockGetTenantsForUser = jest.fn<Promise<string>, [string]>();
const mockSignOut = jest.fn();
const mockRefresh = jest.fn();

jest.mock('../lib/db/helper', () => ({
  getTenantsForUser: (userId: string) => mockGetTenantsForUser(userId),
}));

jest.mock('next-auth/react', () => ({
  signOut: (...args: unknown[]) => mockSignOut(...args),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mockRefresh }),
}));

// Mocked explicitly: the `^@lib/` moduleNameMapper outranks the shared
// server-session mock mapping, so the guard would otherwise pull in next-auth.
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => null),
}));

import { getAuthSession } from '@lib/auth/server-session';
import FirstTenantOnboardingGuard from '@/app/components/auth/FirstTenantOnboardingGuard';
import FirstTenantOnboardingPrompt from '@/app/components/auth/FirstTenantOnboardingPrompt';

const mockGetAuthSession = getAuthSession as jest.Mock;

const sessionFor = (userId: string) => ({ user: { user_id: userId } });
const tenantRows = (...tenants: Array<{ id: string; name: string }>) => JSON.stringify(tenants);

/** Renders the async server component the way React would: awaited, then mounted. */
const renderGuard = async (children: React.ReactNode = <div data-testid="route-content" />) =>
  render(await FirstTenantOnboardingGuard({ children }));

beforeEach(() => {
  mockGetTenantsForUser.mockReset();
  mockSignOut.mockReset();
  mockRefresh.mockReset();
  mockGetAuthSession.mockReset();
});

describe('FirstTenantOnboardingGuard', () => {
  it('prompts the onboarding wizard for an authenticated user with zero memberships', async () => {
    mockGetAuthSession.mockResolvedValueOnce(sessionFor('user-1'));
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows());

    await renderGuard();

    expect(screen.getByTestId('first-tenant-onboarding-prompt')).toBeInTheDocument();
    expect(screen.queryByTestId('route-content')).not.toBeInTheDocument();
  });

  it('renders the route content for a tenant member', async () => {
    mockGetAuthSession.mockResolvedValueOnce(sessionFor('user-1'));
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows({ id: 't1', name: 'Acme' }));

    await renderGuard();

    expect(screen.getByTestId('route-content')).toBeInTheDocument();
    expect(screen.queryByTestId('first-tenant-onboarding-prompt')).not.toBeInTheDocument();
  });

  it('renders the route content when there is no authenticated session', async () => {
    mockGetAuthSession.mockResolvedValueOnce(null);

    await renderGuard();

    expect(screen.getByTestId('route-content')).toBeInTheDocument();
    expect(mockGetTenantsForUser).not.toHaveBeenCalled();
  });

  it('fails open to the route content when the membership lookup throws', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetAuthSession.mockResolvedValueOnce(sessionFor('user-1'));
    mockGetTenantsForUser.mockRejectedValueOnce(new Error('db down'));

    await renderGuard();

    expect(screen.getByTestId('route-content')).toBeInTheDocument();
    consoleError.mockRestore();
  });
});

describe('FirstTenantOnboardingPrompt', () => {
  it('re-checks memberships via a server refresh', () => {
    render(<FirstTenantOnboardingPrompt />);

    fireEvent.click(screen.getByRole('button', { name: /check again/i }));

    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it('signs the user out back to the login page', () => {
    render(<FirstTenantOnboardingPrompt />);

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(mockSignOut).toHaveBeenCalledWith({ callbackUrl: '/login' });
  });

  it('offers no dismiss control — the prompt is not skippable', () => {
    render(<FirstTenantOnboardingPrompt />);

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(screen.getByRole('heading', { name: /set up your first tenant/i })).toBeInTheDocument();
  });
});
