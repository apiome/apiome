/**
 * The `apiome login` approve page (#5501): pure helpers, the server actions' REST contract, and
 * every state of the screen.
 *
 * Docs fixtures (`apiome-docs/screens.json`, `cli-login*`) are dumped from here:
 *
 *     A11Y_FIXTURE_DUMP=1 npx jest tests/cli-login.test.tsx
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockGet = jest.fn();
const mockApprove = jest.fn();
const mockDeny = jest.fn();

jest.mock('@lib/auth/cli-login-actions', () => ({
  getCliLoginRequest: (...args: unknown[]) => mockGet(...args),
  approveCliLogin: (...args: unknown[]) => mockApprove(...args),
  denyCliLogin: (...args: unknown[]) => mockDeny(...args),
}));
jest.mock('@/app/hooks/useDarkMode', () => ({ useDarkMode: () => false }));

import CliLoginClient from '../src/app/cli/login/CliLoginClient';
import {
  cliLoginPagePath,
  defaultCliLoginWorkspace,
  normalizeCliUserCode,
  type CliLoginRequest,
} from '../lib/auth/cli-login';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const REQUEST: CliLoginRequest = {
  user_code: 'KTXR-MWDB',
  client_name: 'apiome-cli on build-box',
  status: 'pending',
  created_at: '2026-10-23T17:00:00Z',
  expires_at: '2026-10-23T17:10:00Z',
  workspaces: [
    { slug: 'northwind', name: 'Northwind', can_approve: true },
    { slug: 'harbor', name: 'Harbor Labs', can_approve: true },
    { slug: 'quayside', name: 'Quayside', can_approve: false },
  ],
};

beforeEach(() => {
  mockGet.mockReset();
  mockApprove.mockReset();
  mockDeny.mockReset();
});

describe('pure helpers', () => {
  it.each([
    ['ktxr-mwdb', 'KTXR-MWDB'],
    [' KTXR MWDB ', 'KTXR-MWDB'],
    ['KTXRMWDB', 'KTXR-MWDB'],
    ['KTXR-MWD', null],
    ['KTXR-MW!B', null],
    [undefined, null],
  ])('normalizes %p to %p', (raw, expected) => {
    expect(normalizeCliUserCode(raw)).toBe(expected);
  });

  it('builds the page path for the sign-in round trip', () => {
    expect(cliLoginPagePath('KTXR-MWDB')).toBe('/cli/login?code=KTXR-MWDB');
    expect(cliLoginPagePath(null)).toBe('/cli/login');
  });

  it('preselects the current workspace only when it may be approved for', () => {
    expect(defaultCliLoginWorkspace(REQUEST.workspaces, 'harbor')).toBe('harbor');
    expect(defaultCliLoginWorkspace(REQUEST.workspaces, 'quayside')).toBe('northwind');
    expect(defaultCliLoginWorkspace(REQUEST.workspaces, null)).toBe('northwind');
    expect(defaultCliLoginWorkspace([{ slug: 'q', name: 'Q', can_approve: false }], 'q')).toBeNull();
  });
});

describe('the approve screen', () => {
  it('reads the login from the URL code and shows it for comparison', async () => {
    mockGet.mockResolvedValue({ ok: true, data: REQUEST });
    const { container } = render(<CliLoginClient initialCode="KTXR-MWDB" currentWorkspaceSlug="northwind" />);

    expect(await screen.findByTestId('cli-login-review')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledWith('KTXR-MWDB');
    expect(screen.getByTestId('cli-login-code')).toHaveTextContent('KTXR-MWDB');
    expect(screen.getByText(/apiome-cli on build-box is asking to act as you/)).toBeInTheDocument();
    expect(screen.getByTestId('cli-login-workspace')).toHaveTextContent('Northwind');
    expect(screen.getByText(/lasts 14 days/)).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('cli-login', container.innerHTML);
  });

  it('approves for the chosen workspace and sends the person back to the terminal', async () => {
    mockApprove.mockResolvedValue({ ok: true, data: { user_code: 'KTXR-MWDB', status: 'approved', tenant_slug: 'northwind' } });
    const { container } = render(
      <CliLoginClient initialCode="KTXR-MWDB" currentWorkspaceSlug="northwind" initialRequest={REQUEST} />
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('cli-login-approve'));
    });
    expect(mockApprove).toHaveBeenCalledWith('KTXR-MWDB', 'northwind');
    expect(screen.getByTestId('cli-login-approved')).toHaveTextContent('CLI signed in');
    expect(screen.getByTestId('cli-login-approved')).toHaveTextContent('signed in to Northwind');
    expect(mockGet).not.toHaveBeenCalled();
    writeA11yFixture('cli-login-approved', container.innerHTML);
  });

  it('denies', async () => {
    mockDeny.mockResolvedValue({ ok: true, data: { user_code: 'KTXR-MWDB', status: 'denied' } });
    render(<CliLoginClient initialCode="KTXR-MWDB" currentWorkspaceSlug={null} initialRequest={REQUEST} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('cli-login-deny'));
    });
    expect(mockDeny).toHaveBeenCalledWith('KTXR-MWDB');
    expect(screen.getByTestId('cli-login-denied')).toHaveTextContent('Login denied');
  });

  it('shows a refusal from the server beside the buttons', async () => {
    mockApprove.mockResolvedValue({ ok: false, reason: 'forbidden', message: 'You need permission to create API keys.' });
    render(<CliLoginClient initialCode="KTXR-MWDB" currentWorkspaceSlug={null} initialRequest={REQUEST} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('cli-login-approve'));
    });
    expect(screen.getByTestId('cli-login-error')).toHaveTextContent('You need permission to create API keys.');
    expect(screen.getByTestId('cli-login-review')).toBeInTheDocument();
  });

  it('offers only Deny when no workspace may be approved for', () => {
    const request = { ...REQUEST, workspaces: [{ slug: 'quayside', name: 'Quayside', can_approve: false }] };
    render(<CliLoginClient initialCode="KTXR-MWDB" currentWorkspaceSlug={null} initialRequest={request} />);
    expect(screen.getByTestId('cli-login-no-workspace')).toHaveTextContent('cannot create API keys');
    expect(screen.queryByTestId('cli-login-approve')).not.toBeInTheDocument();
    expect(screen.getByTestId('cli-login-deny')).toBeEnabled();
  });

  it('says so when a code is not waiting, and lets the person enter another', async () => {
    mockGet.mockResolvedValue({ ok: false, reason: 'not-found', message: 'This code is not waiting for approval.' });
    render(<CliLoginClient initialCode="BCDF-GHJK" currentWorkspaceSlug={null} />);
    expect(await screen.findByTestId('cli-login-missing')).toHaveTextContent('This code is not waiting');
    fireEvent.click(screen.getByRole('button', { name: 'Enter another code' }));
    expect(screen.getByTestId('cli-login-enter')).toBeInTheDocument();
  });

  it('asks for the code when opened without one, and checks its shape first', async () => {
    mockGet.mockResolvedValue({ ok: true, data: REQUEST });
    const { container } = render(<CliLoginClient initialCode={null} currentWorkspaceSlug={null} />);
    expect(mockGet).not.toHaveBeenCalled();
    writeA11yFixture('cli-login-enter', container.innerHTML);

    const field = screen.getByLabelText('Code');
    fireEvent.change(field, { target: { value: 'nope' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByText(/8-character code/)).toBeInTheDocument();
    expect(mockGet).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: 'ktxr mwdb' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    });
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('KTXR-MWDB'));
    expect(await screen.findByTestId('cli-login-review')).toBeInTheDocument();
  });
});
