/**
 * AuthenticatedLayout session-expiry tests (OLO-3.4, #4202).
 *
 * The /ade shell's client-side auth guard must (a) render protected content
 * only for an authenticated session, and (b) when the session is gone —
 * expired, revoked, or signed out in another tab — redirect to /login with the
 * current location preserved as callbackUrl so signing back in returns the
 * user to the page they were on.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockUseSession = jest.fn();
const mockPush = jest.fn();
let mockPathname = '/ade/dashboard/projects';

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  useAuthSession: () => mockUseSession(),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => mockPathname,
}));

import AuthenticatedLayout from '@/app/components/auth/AuthenticatedLayout';

/** Puts jsdom's window.location on the given path + query. */
const setLocation = (path: string) => {
  window.history.pushState({}, '', path);
};

beforeEach(() => {
  mockUseSession.mockReset();
  mockPush.mockReset();
  mockPathname = '/ade/dashboard/projects';
  setLocation('/ade/dashboard/projects');
});

describe('AuthenticatedLayout', () => {
  it('renders children for an authenticated session', () => {
    mockUseSession.mockReturnValue({ data: { user: { name: 'Kai' } }, status: 'authenticated' });

    render(
      <AuthenticatedLayout>
        <div data-testid="protected" />
      </AuthenticatedLayout>
    );

    expect(screen.getByTestId('protected')).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('shows the loading state (and no redirect) while the session is loading', () => {
    mockUseSession.mockReturnValue({ data: undefined, status: 'loading' });

    render(
      <AuthenticatedLayout>
        <div data-testid="protected" />
      </AuthenticatedLayout>
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('redirects an expired session to /login preserving the current location', async () => {
    mockUseSession.mockReturnValue({ data: null, status: 'unauthenticated' });
    setLocation('/ade/dashboard/projects?tab=archived');

    render(
      <AuthenticatedLayout>
        <div data-testid="protected" />
      </AuthenticatedLayout>
    );

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith(
        `/login?callbackUrl=${encodeURIComponent('/ade/dashboard/projects?tab=archived')}`
      )
    );
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
  });

  it('redirects without a callbackUrl when no pathname is available', async () => {
    mockUseSession.mockReturnValue({ data: null, status: 'unauthenticated' });
    mockPathname = '';
    setLocation('/');

    render(<AuthenticatedLayout>content</AuthenticatedLayout>);

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/login'));
  });

  it('honors an explicit redirectTo verbatim', async () => {
    mockUseSession.mockReturnValue({ data: null, status: 'unauthenticated' });

    render(<AuthenticatedLayout redirectTo="/custom-login">content</AuthenticatedLayout>);

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/custom-login'));
  });
});
