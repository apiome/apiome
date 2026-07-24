/**
 * Login page SSO button rendering tests (OLO-2.3, #4195).
 *
 * The login page resolves the enabled providers server-side from the provider registry and
 * passes them to `LoginClient`, which renders exactly one SSO button per enabled provider.
 * These tests pin the acceptance criteria at the UI: the buttons track the given provider
 * list (not hardcoded), each button starts the right NextAuth flow, and an env with no
 * enabled providers renders a credentials-only page.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockSignIn = jest.fn();

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  signIn: (...args: unknown[]) => mockSignIn(...args),
}));

jest.mock('../lib/db/helper', () => ({
  createSignupRequest: jest.fn(),
}));

jest.mock('@/app/hooks/useDarkMode', () => ({
  useDarkMode: () => false,
}));

import LoginClient from '../src/app/login/LoginClient';
import type { ProviderSummary } from '../lib/auth/provider-registry';

const summary = (id: string, label: string): ProviderSummary => ({
  id,
  label,
  status: 'available',
  enabled: true,
});

beforeEach(() => {
  mockSignIn.mockReset();
});

describe('LoginClient — SSO buttons from the provider registry (OLO-2.3)', () => {
  it('renders exactly one button per enabled provider, in order', () => {
    render(
      <LoginClient
        ssoProviders={[
          summary('github', 'GitHub'),
          summary('gitlab', 'GitLab'),
          summary('azure', 'Microsoft'),
        ]}
      />
    );

    const buttons = screen.getAllByRole('button', { name: /^Continue with / });
    expect(buttons.map((b) => b.textContent)).toEqual([
      'Continue with GitHub',
      'Continue with GitLab',
      'Continue with Microsoft',
    ]);
  });

  it('omits providers not in the list (env-disabled providers never render)', () => {
    render(<LoginClient ssoProviders={[summary('github', 'GitHub')]} />);

    expect(screen.getByRole('button', { name: 'Continue with GitHub' })).toBeInTheDocument();
    expect(screen.queryByText('Continue with GitLab')).not.toBeInTheDocument();
    expect(screen.queryByText('Continue with Microsoft')).not.toBeInTheDocument();
  });

  it('hides the SSO block and its divider when no provider is enabled', () => {
    render(<LoginClient ssoProviders={[]} />);

    expect(screen.queryByRole('button', { name: /^Continue with / })).not.toBeInTheDocument();
    expect(screen.queryByText('or use your email')).not.toBeInTheDocument();
    // The credentials form still works as the only path.
    expect(screen.getByRole('button', { name: /Sign In/ })).toBeInTheDocument();
  });

  it('defaults to no SSO buttons when the prop is omitted', () => {
    render(<LoginClient />);
    expect(screen.queryByRole('button', { name: /^Continue with / })).not.toBeInTheDocument();
  });

  it('starts the NextAuth flow for the clicked provider id', () => {
    render(<LoginClient ssoProviders={[summary('azure', 'Microsoft')]} callbackUrl="/ade" />);

    fireEvent.click(screen.getByRole('button', { name: 'Continue with Microsoft' }));
    expect(mockSignIn).toHaveBeenCalledWith('azure', { callbackUrl: '/ade' });
  });

  it('labels buttons for sign-up mode', () => {
    render(<LoginClient ssoProviders={[summary('github', 'GitHub')]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Create one' }));
    expect(screen.getByRole('button', { name: 'Sign up with GitHub' })).toBeInTheDocument();
  });
});
