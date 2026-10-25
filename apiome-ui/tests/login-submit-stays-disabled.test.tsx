/**
 * The login form's **Sign In** button stays disabled once clicked: `signIn` navigates on every
 * outcome, so re-enabling it when the promise settled invited a second click mid-navigation.
 * It comes back only when `signIn` throws and the page stays put.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockSignIn = jest.fn();

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  signIn: (...args: unknown[]) => mockSignIn(...args),
}));
jest.mock('../lib/db/helper', () => ({}));
jest.mock('@/app/hooks/useDarkMode', () => ({ useDarkMode: () => false }));

import LoginClient from '../src/app/login/LoginClient';

const submitButton = () => screen.getByRole('button', { name: /Sign In/ });

function submitCredentials() {
  fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'ada@example.com' } });
  fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'Analytical1' } });
  fireEvent.click(submitButton());
}

beforeEach(() => {
  mockSignIn.mockReset();
  jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => jest.restoreAllMocks());

describe('LoginClient — Sign In while the browser navigates', () => {
  it('stays disabled after signIn resolves, so it cannot be clicked twice', async () => {
    mockSignIn.mockResolvedValue(undefined);
    render(<LoginClient ssoProviders={[]} />);
    submitCredentials();

    await waitFor(() => expect(mockSignIn).toHaveBeenCalledTimes(1));
    await Promise.resolve();
    expect(submitButton()).toBeDisabled();
    fireEvent.click(submitButton());
    expect(mockSignIn).toHaveBeenCalledTimes(1);
  });

  it('re-enables when signIn throws', async () => {
    mockSignIn.mockRejectedValue(new Error('network'));
    render(<LoginClient ssoProviders={[]} />);
    submitCredentials();

    await waitFor(() => expect(submitButton()).toBeEnabled());
    expect(mockSignIn).toHaveBeenCalledTimes(1);
  });
});
