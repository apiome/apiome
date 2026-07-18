/**
 * First-tenant onboarding route guard tests (OLO-3.3 #4201, OLO-4.1 #4205).
 *
 * The guard implements the zero-tenant half of the post-login routing rules on
 * the /ade shell: authenticated users with no tenant memberships see the
 * first-tenant onboarding wizard in place of any route content (so deep links
 * cannot route around it), while members, signed-out visitors, and
 * membership-store failures all render the route unchanged. Wizard behavior
 * itself is covered in `first-tenant-onboarding-wizard.test.tsx`.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockGetTenantsForUser = jest.fn<Promise<string>, [string]>();

jest.mock('../lib/db/helper', () => ({
  getTenantsForUser: (userId: string) => mockGetTenantsForUser(userId),
}));

jest.mock('next-auth/react', () => ({
  signOut: jest.fn(),
  useSession: () => ({ data: null, status: 'authenticated', update: jest.fn() }),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

// Mocked so the guard's client-side wizard subtree doesn't pull the db-backed
// server action module into a jsdom test.
jest.mock('@lib/auth/first-tenant-actions', () => ({
  provisionFirstTenant: jest.fn(),
}));

// Mocked explicitly: the `^@lib/` moduleNameMapper outranks the shared
// server-session mock mapping, so the guard would otherwise pull in next-auth.
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => null),
}));

import { getAuthSession } from '@lib/auth/server-session';
import FirstTenantOnboardingGuard from '@/app/components/auth/FirstTenantOnboardingGuard';

const mockGetAuthSession = getAuthSession as jest.Mock;

const sessionFor = (userId: string) => ({ user: { user_id: userId } });
const tenantRows = (...tenants: Array<{ id: string; name: string }>) => JSON.stringify(tenants);

/** Renders the async server component the way React would: awaited, then mounted. */
const renderGuard = async (children: React.ReactNode = <div data-testid="route-content" />) =>
  render(await FirstTenantOnboardingGuard({ children }));

beforeEach(() => {
  mockGetTenantsForUser.mockReset();
  mockGetAuthSession.mockReset();
});

describe('FirstTenantOnboardingGuard', () => {
  it('prompts the onboarding wizard for an authenticated user with zero memberships', async () => {
    mockGetAuthSession.mockResolvedValueOnce(sessionFor('user-1'));
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows());

    await renderGuard();

    expect(screen.getByTestId('first-tenant-onboarding-wizard')).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-step-welcome')).toBeInTheDocument();
    expect(screen.queryByTestId('route-content')).not.toBeInTheDocument();
  });

  it('renders the route content for a tenant member', async () => {
    mockGetAuthSession.mockResolvedValueOnce(sessionFor('user-1'));
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows({ id: 't1', name: 'Acme' }));

    await renderGuard();

    expect(screen.getByTestId('route-content')).toBeInTheDocument();
    expect(screen.queryByTestId('first-tenant-onboarding-wizard')).not.toBeInTheDocument();
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
