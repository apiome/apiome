/**
 * The shared ownership controls — CDG-2.4 (#5963): the Owner cell (with inline confirm), the owner
 * filter and the bulk "Assign owner" control.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { AssignOwnerControl, OwnerCell, OwnerFilter } from '../src/app/components/ade/owners';
import type { EntityOwner, Team } from '../lib/owners';

const TEAMS: Team[] = [
  { id: 't-1', slug: 'payments', name: 'Payments', member_count: 2 },
  { id: 't-2', slug: 'platform', name: 'Platform', member_count: 1 },
];
const SUGGESTED: EntityOwner = {
  team: { id: 't-1', slug: 'payments', name: 'Payments' },
  status: 'suggested',
  source: 'gateway_tag',
};

let confirmReply: { ok: boolean; body: unknown } = { ok: true, body: {} };
let posted: Array<{ url: string; body: unknown }> = [];

beforeEach(() => {
  posted = [];
  confirmReply = {
    ok: true,
    body: { owner: { ...SUGGESTED, status: 'confirmed' }, suggestions: [] },
  };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    posted.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
    return { ok: confirmReply.ok, status: confirmReply.ok ? 200 : 403, json: async () => confirmReply.body } as Response;
  }) as unknown as typeof fetch;
});

describe('the owner cell', () => {
  test('a confirmed owner is the team, linking to its page, with nothing to confirm', () => {
    render(<OwnerCell owner={{ ...SUGGESTED, status: 'confirmed' }} kind="project" entityId="p-1" />);
    expect(screen.getByRole('link', { name: 'Payments' })).toHaveAttribute('href', '/ade/dashboard/teams/payments');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByText(/Suggested/)).not.toBeInTheDocument();
  });

  test('no owner is a dash that says so', () => {
    render(<OwnerCell owner={null} kind="project" entityId="p-1" />);
    expect(screen.getByTestId('owner-cell')).toHaveTextContent('No owner');
  });

  test('a suggestion names its source and confirms in place', async () => {
    const user = userEvent.setup();
    const changes: Array<EntityOwner | null> = [];
    const { container } = render(
      <OwnerCell owner={SUGGESTED} kind="catalog_item" entityId="c-1" onChange={(owner) => changes.push(owner)} />
    );
    expect(screen.getByText('Suggested · Gateway tag')).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByRole('button', { name: 'Confirm Payments as owner' }));
    await waitFor(() => expect(changes).toHaveLength(1));
    expect(changes[0]?.status).toBe('confirmed');
    expect(posted).toEqual([{ url: '/api/owners/catalog_item/c-1/confirm', body: { team: 'payments' } }]);
  });

  test('a refused confirm says why and changes nothing', async () => {
    const user = userEvent.setup();
    confirmReply = { ok: false, body: { error: 'Permission denied: projects:edit is required' } };
    const changes: unknown[] = [];
    render(<OwnerCell owner={SUGGESTED} kind="project" entityId="p-1" onChange={(owner) => changes.push(owner)} />);
    await user.click(screen.getByRole('button', { name: 'Confirm Payments as owner' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('projects:edit');
    expect(changes).toEqual([]);
  });

  test('read-only hides Confirm', () => {
    render(<OwnerCell owner={SUGGESTED} kind="project" entityId="p-1" readOnly />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('the owner filter', () => {
  test('offers every team and reports the choice', async () => {
    const user = userEvent.setup();
    const chosen: Array<string | null> = [];
    const { container } = render(<OwnerFilter teams={TEAMS} value={null} onChange={(team) => chosen.push(team)} />);
    expect(screen.getByLabelText('Owner')).toHaveValue('');
    await user.selectOptions(screen.getByLabelText('Owner'), 'platform');
    await user.selectOptions(screen.getByLabelText('Owner'), '');
    expect(chosen).toEqual(['platform', null]);
    expect(await axe(container)).toHaveNoViolations();
  });

  test('keeps a slug from the URL that names no loaded team, so it can be cleared', () => {
    render(<OwnerFilter teams={TEAMS} value="ghost" onChange={() => undefined} />);
    expect(screen.getByLabelText('Owner')).toHaveValue('ghost');
  });
});

describe('the bulk assign control', () => {
  test('assigns only once a team is chosen', async () => {
    const user = userEvent.setup();
    const assigned: string[] = [];
    render(<AssignOwnerControl teams={TEAMS} onAssign={(team) => void assigned.push(team)} />);
    expect(screen.getByTestId('bulk-assign-owner')).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Team to assign as owner'), 'payments');
    await user.click(screen.getByTestId('bulk-assign-owner'));
    expect(assigned).toEqual(['payments']);
  });
});
