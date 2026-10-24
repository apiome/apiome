/**
 * The tenant drawer's **Security** section — TFA-1.3 (#5657).
 *
 * Reads the policy, turns the requirement on with a grace period in one PUT, refuses a grace period
 * REST would refuse, shows who still has to comply, and is read-only for non-administrators.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import TenantTwoFactorPolicySection from '../src/app/components/ade/tenants/TenantTwoFactorPolicySection';
import type { TwoFactorPolicy } from '../lib/two-factor-policy';

const OFF: TwoFactorPolicy = {
  require_two_factor: false,
  grace_days: 7,
  required_since: null,
  compliance: { enabled: 0, grace: 0, overdue: 0 },
};

let policy: TwoFactorPolicy = OFF;
let puts: unknown[] = [];

beforeEach(() => {
  window.localStorage.clear();
  policy = OFF;
  puts = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
    if (url === '/api/two-factor-policy' && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body));
      puts.push(body);
      policy = {
        require_two_factor: body.require_two_factor,
        grace_days: body.grace_days,
        required_since: body.require_two_factor ? '2026-10-23T12:00:00Z' : null,
        compliance: body.require_two_factor ? { enabled: 3, grace: 1, overdue: 1 } : OFF.compliance,
      };
      return reply(policy);
    }
    if (url === '/api/two-factor-policy') return reply(policy);
    return { ok: false, status: 404, json: async () => ({ error: 'not found' }) } as Response;
  }) as unknown as typeof fetch;
});

/** Render the section and wait for the policy to load. */
const renderSection = async (isAdmin = true) => {
  const view = render(
    <TenantTwoFactorPolicySection isAdmin={isAdmin} membersPageHref="/ade/dashboard/members" />
  );
  await screen.findByRole('switch', { name: 'Require two-factor' });
  return view;
};

describe('TenantTwoFactorPolicySection', () => {
  it('loads the policy off, with the 7-day default and nothing to save', async () => {
    await renderSection();

    expect(screen.getByRole('switch', { name: 'Require two-factor' })).not.toBeChecked();
    expect(screen.getByLabelText('Grace period (days)')).toHaveValue(7);
    expect(screen.getByTestId('tenant-two-factor-save')).toBeDisabled();
    expect(screen.queryByTestId('tenant-two-factor-compliance')).not.toBeInTheDocument();
  });

  it('turns the requirement on with a grace period in one PUT, then shows compliance', async () => {
    const user = userEvent.setup();
    await renderSection();

    await user.click(screen.getByRole('switch', { name: 'Require two-factor' }));
    expect(screen.getByTestId('tenant-two-factor-turning-on')).toHaveTextContent(
      "Saving starts everyone's grace period now."
    );
    const grace = screen.getByLabelText('Grace period (days)');
    await user.clear(grace);
    await user.type(grace, '14');
    await user.click(screen.getByTestId('tenant-two-factor-save'));

    await waitFor(() => expect(puts).toEqual([{ require_two_factor: true, grace_days: 14 }]));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved.');
    const compliance = screen.getByRole('list', { name: 'Two-factor compliance' });
    expect(compliance).toHaveTextContent('3 with two-factor');
    expect(compliance).toHaveTextContent('1 in grace period');
    expect(compliance).toHaveTextContent('1 overdue');
    expect(screen.getByRole('link', { name: 'See who on the Members page' })).toHaveAttribute(
      'href',
      '/ade/dashboard/members'
    );
  });

  it.each(['', '91', '-1', '2.5'])('refuses a grace period of %p', async (value) => {
    const user = userEvent.setup();
    await renderSection();

    const grace = screen.getByLabelText('Grace period (days)');
    await user.clear(grace);
    if (value) await user.type(grace, value);

    expect(grace).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Enter a whole number of days from 0 to 90.')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-two-factor-save')).toBeDisabled();
  });

  it('is read-only for someone who does not administer the workspace', async () => {
    await renderSection(false);

    expect(screen.getByText('Only administrators can change the two-factor policy.')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Require two-factor' })).toBeDisabled();
    expect(screen.getByLabelText('Grace period (days)')).toBeDisabled();
    expect(screen.queryByTestId('tenant-two-factor-save')).not.toBeInTheDocument();
  });

  it('says so when the policy cannot be loaded', async () => {
    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 403,
      json: async () => ({ error: 'Permission denied: members:view' }),
    })) as unknown as typeof fetch;
    render(<TenantTwoFactorPolicySection isAdmin membersPageHref="/ade/dashboard/members" />);

    expect(await screen.findByText('Permission denied: members:view')).toBeInTheDocument();
  });

  it('has no axe violations with the requirement on', async () => {
    policy = {
      require_two_factor: true,
      grace_days: 7,
      required_since: '2026-10-20T12:00:00Z',
      compliance: { enabled: 6, grace: 2, overdue: 1 },
    };
    const { container } = await renderSection();
    await screen.findByTestId('tenant-two-factor-compliance');

    expect(await axe(container)).toHaveNoViolations();
  });
});
