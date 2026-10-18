/**
 * The ownership policy in the UI — CDG-2.5 (#5964).
 *
 * - the tenant drawer's **Ownership** section reads the policy and the teams, saves both settings in
 *   one PUT, warns when the catch-all team was deleted, and is read-only for non-administrators;
 * - the publish dialog's **Owner team** card always states where the gate stands — off, met or
 *   blocked — never staying silent.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import TenantOwnershipPolicySection from '../src/app/components/ade/tenants/TenantOwnershipPolicySection';
import { OwnerGatePanel } from '../src/app/components/ade/owners/OwnerGatePanel';
import type { OwnerGate, OwnershipPolicy } from '../lib/owners';

const TEAMS = [
  { id: 't-1', slug: 'payments', name: 'Payments', member_count: 3 },
  { id: 't-2', slug: 'platform', name: 'Platform', member_count: 5 },
];

let policy: OwnershipPolicy = { unowned_findings_team: null, require_owner_to_publish: false };
let gate: OwnerGate = { status: 'disabled', message: 'The owner gate is off: publishing does not require an owner team.' };
let puts: unknown[] = [];

beforeEach(() => {
  policy = { unowned_findings_team: null, require_owner_to_publish: false };
  puts = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
    if (url === '/api/teams') return reply({ teams: TEAMS, count: 2 });
    if (url === '/api/ownership-policy' && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body));
      puts.push(body);
      const team = TEAMS.find((entry) => entry.slug === body.unowned_findings_team);
      policy = {
        unowned_findings_team: team ? { ...team, deleted: false } : null,
        require_owner_to_publish: body.require_owner_to_publish,
      };
      return reply(policy);
    }
    if (url === '/api/ownership-policy') return reply(policy);
    if (url.startsWith('/api/ownership-policy/publish-gate')) return reply(gate);
    return { ok: false, status: 404, json: async () => ({ error: 'not found' }) } as Response;
  }) as unknown as typeof fetch;
});

describe('the tenant drawer’s Ownership section', () => {
  test('saves the catch-all team and the publish gate together', async () => {
    const user = userEvent.setup();
    render(<TenantOwnershipPolicySection isAdmin />);
    const select = await screen.findByTestId('tenant-catch-all');
    await waitFor(() => expect(screen.getByRole('option', { name: 'Platform' })).toBeInTheDocument());
    expect(screen.getByTestId('tenant-ownership-save')).toBeDisabled();

    await user.selectOptions(select, 'platform');
    await user.click(screen.getByLabelText('Require an owner to publish'));
    await user.click(screen.getByTestId('tenant-ownership-save'));

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved.'));
    expect(puts).toEqual([{ unowned_findings_team: 'platform', require_owner_to_publish: true }]);
    expect(screen.getByTestId('tenant-ownership-save')).toBeDisabled();
  });

  test('warns when the catch-all team was deleted', async () => {
    policy = {
      unowned_findings_team: { id: 't-9', slug: 'old', name: 'Old team', deleted: true },
      require_owner_to_publish: false,
    };
    render(<TenantOwnershipPolicySection isAdmin />);
    expect(await screen.findByTestId('tenant-catch-all-deleted')).toHaveTextContent('Old team was deleted');
  });

  test('is read-only for a non-administrator', async () => {
    render(<TenantOwnershipPolicySection isAdmin={false} />);
    expect(await screen.findByTestId('tenant-catch-all')).toBeDisabled();
    expect(screen.getByText('Only administrators can change the ownership policy.')).toBeInTheDocument();
    expect(screen.queryByTestId('tenant-ownership-save')).not.toBeInTheDocument();
  });

  test('passes axe', async () => {
    const { container } = render(<TenantOwnershipPolicySection isAdmin />);
    await screen.findByTestId('tenant-catch-all');
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('the publish dialog’s owner gate', () => {
  test.each([
    ['disabled', 'Off', 'The owner gate is off'],
    ['satisfied', 'Met', 'Owned by Payments.'],
    ['blocked', 'Blocked', 'no confirmed owner team'],
  ] as const)('%s says so', async (status, badge, text) => {
    gate = {
      status,
      message:
        status === 'disabled'
          ? 'The owner gate is off: publishing does not require an owner team.'
          : status === 'satisfied'
            ? 'Owned by Payments.'
            : 'This project has no confirmed owner team, and the workspace requires one to publish.',
      ...(status === 'blocked' ? { reason: 'no-owner' } : {}),
    };
    render(<OwnerGatePanel projectId="22222222-2222-4222-8222-222222222222" enabled />);
    expect(await screen.findByTestId('owner-gate-status')).toHaveTextContent(badge);
    expect(screen.getByTestId('owner-gate-message')).toHaveTextContent(text);
    expect(Boolean(screen.queryByText(/Publishing will be refused/))).toBe(status === 'blocked');
  });

  test('reads nothing while the dialog is closed', () => {
    render(<OwnerGatePanel projectId="22222222-2222-4222-8222-222222222222" enabled={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
