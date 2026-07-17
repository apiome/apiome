/**
 * Login page credentials-collapse and redirect-state tests (OLO-3.1, #4199).
 *
 * With SSO as the primary path, the credentials form starts collapsed beneath the "or"
 * divider and the divider doubles as the expand control. These tests pin that behavior:
 * the form is collapsed exactly when SSO buttons render (except after a failed credentials
 * attempt), expansion is one-way, and every credentials/expand control is disabled while an
 * SSO redirect is in progress.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockSignIn = jest.fn();

jest.mock('next-auth/react', () => ({
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

const PROVIDERS = [summary('github', 'GitHub'), summary('gitlab', 'GitLab')];

/** The divider's expand control (only present while the form is collapsed). */
const expandButton = () => screen.queryByRole('button', { name: 'or use your email' });

/** The credentials submit button (hidden from the accessibility tree while collapsed). */
const submitButton = () => screen.queryByRole('button', { name: /Sign In/ });

beforeEach(() => {
  mockSignIn.mockReset();
});

describe('LoginClient — collapsed credentials form (OLO-3.1)', () => {
  it('starts collapsed when SSO providers are available', () => {
    render(<LoginClient ssoProviders={PROVIDERS} />);

    expect(expandButton()).toBeInTheDocument();
    expect(submitButton()).not.toBeInTheDocument();
    expect(expandButton()).toHaveAttribute('aria-expanded', 'false');
  });

  it('expands on request and turns the control back into a static divider', () => {
    render(<LoginClient ssoProviders={PROVIDERS} />);

    fireEvent.click(expandButton()!);

    expect(submitButton()).toBeVisible();
    expect(expandButton()).not.toBeInTheDocument();
    // The divider label survives as plain text.
    expect(screen.getByText('or use your email')).toBeInTheDocument();
  });

  it('starts expanded (no expand control) when credentials are the only path', () => {
    render(<LoginClient ssoProviders={[]} />);

    expect(expandButton()).not.toBeInTheDocument();
    expect(submitButton()).toBeVisible();
  });

  it('starts expanded after a failed credentials attempt so the user can retry', () => {
    render(<LoginClient ssoProviders={PROVIDERS} error="CredentialsSignin" />);

    expect(expandButton()).not.toBeInTheDocument();
    expect(submitButton()).toBeVisible();
  });

  it('stays collapsed for SSO-side error codes', () => {
    render(<LoginClient ssoProviders={PROVIDERS} error="unverified-email" />);

    expect(expandButton()).toBeInTheDocument();
    expect(submitButton()).not.toBeInTheDocument();
  });

  it('stays collapsed when switching to sign-up mode', () => {
    render(<LoginClient ssoProviders={PROVIDERS} />);

    fireEvent.click(screen.getByRole('button', { name: 'Create one' }));

    expect(screen.getByRole('button', { name: 'Sign up with GitHub' })).toBeInTheDocument();
    expect(expandButton()).toBeInTheDocument();
    // The sign-up submit ("Create Account") stays collapsed too.
    expect(screen.queryByRole('button', { name: /Create Account/ })).not.toBeInTheDocument();
  });
});

describe('LoginClient — redirect-in-progress state (OLO-3.1)', () => {
  it('shows the connecting state and disables the expand control during an SSO redirect', async () => {
    render(<LoginClient ssoProviders={PROVIDERS} />);

    fireEvent.click(screen.getByRole('button', { name: 'Continue with GitHub' }));

    expect(await screen.findByText('Connecting…')).toBeVisible();
    // The SSO buttons are replaced by the spinner panel.
    expect(screen.queryByRole('button', { name: /^Continue with / })).not.toBeInTheDocument();
    expect(expandButton()).toBeDisabled();
  });

  it('disables the credentials submit and mode toggle during an SSO redirect', async () => {
    render(<LoginClient ssoProviders={PROVIDERS} error="CredentialsSignin" />);

    fireEvent.click(screen.getByRole('button', { name: 'Continue with GitLab' }));

    expect(await screen.findByText('Connecting…')).toBeVisible();
    expect(submitButton()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Create one' })).toBeDisabled();
  });
});
