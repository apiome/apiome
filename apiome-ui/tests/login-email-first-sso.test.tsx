/**
 * Email-first sign-in routing — EID-1.2 (#5012).
 *
 * When any workspace identity provider is routable, the sign-in form asks (debounced) whether the
 * email typed signs in with single sign-on. Pinned:
 * - an email in a verified domain of an enabled provider is offered only "Continue with SSO": the
 *   password field leaves the form and submitting starts SSO, not a credentials sign-in;
 * - an email in any other domain — which is what an unverified or disabled provider's domain is —
 *   keeps the password path;
 * - a submit that beats the debounce is still routed (the lookup is awaited, not raced);
 * - with no routable provider nothing is ever looked up;
 * - a failed lookup leaves the password path; a refused SSO start is said inline;
 * - the routed form has no axe violations and dumps the docs fixture `login-sso-routed`.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockSignIn = jest.fn(() => Promise.resolve());
const mockSignInWithSso = jest.fn();

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  signIn: (...args: unknown[]) => mockSignIn(...(args as [])),
}));
jest.mock('@lib/auth/better-auth-client-compat', () => ({
  signInWithSso: (...args: unknown[]) => mockSignInWithSso(...args),
}));
jest.mock('../lib/db/helper', () => ({}));
jest.mock('@/app/hooks/useDarkMode', () => ({ useDarkMode: () => false }));

import LoginClient from '../src/app/login/LoginClient';
import { SSO_NO_PROVIDER_MESSAGE } from '../src/app/login/EnterpriseSsoSignIn';
import { SSO_DOMAIN_LOOKUP_URL, SSO_LOOKUP_DEBOUNCE_MS } from '../src/app/login/useSsoEmailRouting';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

/** Domains the fake lookup routes to SSO, and the addresses it was asked about. */
let routed: Set<string>;
let asked: string[];
let lookupFails: boolean;

beforeEach(() => {
  jest.useFakeTimers();
  mockSignIn.mockClear();
  mockSignInWithSso.mockReset();
  routed = new Set(['acme.com']);
  asked = [];
  lookupFails = false;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe(SSO_DOMAIN_LOOKUP_URL);
    if (lookupFails) throw new Error('offline');
    const { email } = JSON.parse(String(init?.body)) as { email: string };
    asked.push(email);
    return { ok: true, json: async () => ({ sso: routed.has(email.split('@')[1].toLowerCase()) }) };
  }) as unknown as typeof fetch;
});

afterEach(() => {
  jest.useRealTimers();
});

/** Open the credentials form and type an email, then let the debounce and the lookup settle. */
async function typeEmail(email: string, settle = true) {
  const expander = screen.queryByRole('button', { name: 'or use your email' });
  if (expander) fireEvent.click(expander);
  fireEvent.change(screen.getByLabelText('Email Address'), { target: { value: email } });
  if (settle) {
    await act(async () => {
      jest.advanceTimersByTime(SSO_LOOKUP_DEBOUNCE_MS);
    });
  }
}

const submit = () => screen.getByTestId('login-submit');

describe('LoginClient — email-first SSO routing (EID-1.2)', () => {
  it('offers only “Continue with SSO” for an email in a verified domain', async () => {
    render(<LoginClient enterpriseSso callbackUrl="/ade/dashboard" />);
    await typeEmail('ada@acme.com');

    expect(submit()).toHaveTextContent('Continue with SSO');
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
    expect(screen.getByTestId('login-sso-routed')).toHaveTextContent(
      'Your organization signs in with single sign-on.'
    );

    mockSignInWithSso.mockResolvedValue('redirecting');
    await act(async () => {
      fireEvent.click(submit());
    });
    expect(mockSignInWithSso).toHaveBeenCalledWith('ada@acme.com', '/ade/dashboard');
    expect(mockSignIn).not.toHaveBeenCalled();
    // The browser is leaving for the IdP: the button stays off.
    expect(submit()).toBeDisabled();
  });

  it('keeps the password path for any other domain — an unverified one included', async () => {
    render(<LoginClient enterpriseSso />);
    await typeEmail('ada@unverified.example');
    expect(asked).toEqual(['ada@unverified.example']);
    expect(submit()).toHaveTextContent('Sign In');
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.queryByTestId('login-sso-routed')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2' } });
    await act(async () => {
      fireEvent.click(submit());
    });
    expect(mockSignIn).toHaveBeenCalledWith('credentials', expect.objectContaining({ redirect: true }));
    expect(mockSignInWithSso).not.toHaveBeenCalled();
  });

  it('returns to the password when the email changes to another domain', async () => {
    render(<LoginClient enterpriseSso />);
    await typeEmail('ada@acme.com');
    expect(submit()).toHaveTextContent('Continue with SSO');
    await typeEmail('ada@elsewhere.org');
    expect(submit()).toHaveTextContent('Sign In');
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('asks about a domain once, and not until the address is whole', async () => {
    render(<LoginClient enterpriseSso />);
    await typeEmail('ada@acme');
    expect(asked).toEqual([]);
    await typeEmail('ada@acme.com');
    await typeEmail('grace@acme.com');
    expect(asked).toEqual(['ada@acme.com']);
    expect(submit()).toHaveTextContent('Continue with SSO');
  });

  it('routes a submit that beats the debounce', async () => {
    render(<LoginClient enterpriseSso />);
    await typeEmail('ada@acme.com', false);
    // The lookup has not run: the form still shows the password.
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2' } });
    mockSignInWithSso.mockResolvedValue('redirecting');
    await act(async () => {
      fireEvent.click(submit());
    });
    expect(mockSignInWithSso).toHaveBeenCalledWith('ada@acme.com', '/ade');
    expect(mockSignIn).not.toHaveBeenCalled();
  });

  it('never looks anything up when no enterprise provider is routable', async () => {
    render(<LoginClient />);
    await typeEmail('ada@acme.com');
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2' } });
    fireEvent.click(submit());
    expect(global.fetch).not.toHaveBeenCalled();
    expect(mockSignIn).toHaveBeenCalledTimes(1);
  });

  it('leaves the password path when the lookup fails', async () => {
    lookupFails = true;
    render(<LoginClient enterpriseSso />);
    await typeEmail('ada@acme.com');
    expect(submit()).toHaveTextContent('Sign In');
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('says so inline when single sign-on then refuses the address, and lets the reader retry', async () => {
    render(<LoginClient enterpriseSso />);
    await typeEmail('ada@acme.com');
    mockSignInWithSso.mockResolvedValue('no-provider');
    await act(async () => {
      fireEvent.click(submit());
    });
    expect(screen.getByText(SSO_NO_PROVIDER_MESSAGE)).toBeInTheDocument();
    expect(submit()).not.toBeDisabled();
  });

  it('has no axe violations when routed, and dumps the docs fixture `login-sso-routed`', async () => {
    routed.add('northwind.io');
    const { container } = render(<LoginClient enterpriseSso />);
    await typeEmail('priya@northwind.io');
    expect(submit()).toHaveTextContent('Continue with SSO');
    jest.useRealTimers();
    expect(await axe(container)).toHaveNoViolations();
    // React keeps a typed value as a property; the dump needs it as an attribute.
    screen.getByLabelText('Email Address').setAttribute('value', 'priya@northwind.io');
    writeA11yFixture('login-sso-routed', container.innerHTML);
  });
});
