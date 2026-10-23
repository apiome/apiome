/**
 * "Sign in with SSO" on the sign-in page — EID-1.1 (#5011).
 *
 * Pinned: the entry shows only when an enterprise provider is routable; it opens a work-email form;
 * submitting starts Better Auth's SSO sign-in for that email; a domain no provider covers is said
 * inline (no navigation); like the provider buttons it makes SSO the primary path, so the
 * credentials form starts collapsed; and the page stays axe-clean with the form open.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockSignInWithSso = jest.fn();

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  signIn: jest.fn(),
}));
jest.mock('@lib/auth/better-auth-client-compat', () => ({
  signInWithSso: (...args: unknown[]) => mockSignInWithSso(...args),
}));
jest.mock('../lib/db/helper', () => ({}));
jest.mock('@/app/hooks/useDarkMode', () => ({ useDarkMode: () => false }));

import LoginClient from '../src/app/login/LoginClient';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';
import { SSO_NO_PROVIDER_MESSAGE, SSO_START_FAILED_MESSAGE } from '../src/app/login/EnterpriseSsoSignIn';

beforeEach(() => {
  mockSignInWithSso.mockReset();
});

async function openAndSubmit(email: string) {
  fireEvent.click(screen.getByTestId('enterprise-sso-open'));
  fireEvent.change(screen.getByLabelText('Work email'), { target: { value: email } });
  await act(async () => {
    fireEvent.click(screen.getByTestId('enterprise-sso-continue'));
  });
}

describe('LoginClient — enterprise SSO (EID-1.1)', () => {
  it('offers no SSO entry when no enterprise provider is routable', () => {
    render(<LoginClient />);
    expect(screen.queryByTestId('enterprise-sso-open')).not.toBeInTheDocument();
  });

  it('offers “Sign in with SSO”, collapsed until asked', () => {
    render(<LoginClient enterpriseSso />);
    const open = screen.getByRole('button', { name: 'Sign in with SSO' });
    expect(open).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Work email')).not.toBeInTheDocument();
  });

  it('makes SSO the primary path: the credentials form starts collapsed', () => {
    render(<LoginClient enterpriseSso />);
    expect(screen.getByRole('button', { name: 'or use your email' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('starts single sign-on for the work email, with the page’s callback', async () => {
    mockSignInWithSso.mockResolvedValue('redirecting');
    render(<LoginClient enterpriseSso callbackUrl="/ade/dashboard" />);
    await openAndSubmit('ada@acme.com');
    expect(mockSignInWithSso).toHaveBeenCalledWith('ada@acme.com', '/ade/dashboard');
    expect(screen.getByTestId('enterprise-sso-continue')).toHaveTextContent('Redirecting…');
  });

  it('says so inline when no provider covers the domain', async () => {
    mockSignInWithSso.mockResolvedValue('no-provider');
    render(<LoginClient enterpriseSso />);
    await openAndSubmit('ada@nowhere.test');
    expect(screen.getByText(SSO_NO_PROVIDER_MESSAGE)).toBeInTheDocument();
    expect(screen.getByLabelText('Work email')).toHaveAttribute('aria-invalid', 'true');
    // Typing again clears it.
    fireEvent.change(screen.getByLabelText('Work email'), { target: { value: 'ada@acme.com' } });
    expect(screen.queryByText(SSO_NO_PROVIDER_MESSAGE)).not.toBeInTheDocument();
  });

  it('says so when single sign-on could not start', async () => {
    mockSignInWithSso.mockResolvedValue('failed');
    render(<LoginClient enterpriseSso />);
    await openAndSubmit('ada@acme.com');
    expect(screen.getByText(SSO_START_FAILED_MESSAGE)).toBeInTheDocument();
  });

  it('cannot submit an empty email', () => {
    render(<LoginClient enterpriseSso />);
    fireEvent.click(screen.getByTestId('enterprise-sso-open'));
    expect(screen.getByTestId('enterprise-sso-continue')).toBeDisabled();
  });

  it('renders the docs fixture: the SSO form open with a work email typed (`login-sso`)', () => {
    const { container } = render(<LoginClient enterpriseSso />);
    fireEvent.click(screen.getByTestId('enterprise-sso-open'));
    fireEvent.change(screen.getByLabelText('Work email'), { target: { value: 'ada@northwind.io' } });
    // React keeps a typed value as a property; the dump needs it as an attribute.
    screen.getByLabelText('Work email').setAttribute('value', 'ada@northwind.io');
    writeA11yFixture('login-sso', container.innerHTML);
  });

  it('has no axe violations with the SSO form open', async () => {
    const { container } = render(<LoginClient enterpriseSso />);
    fireEvent.click(screen.getByTestId('enterprise-sso-open'));
    expect(await axe(container)).toHaveNoViolations();
  });
});
