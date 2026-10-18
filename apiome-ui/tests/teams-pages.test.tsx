/**
 * Workspace → Teams — CDG-2.4 (#5963).
 *
 * `/ade/dashboard/teams` lists every team with its members and links; `/ade/dashboard/teams/[slug]`
 * shows one team's open findings, members, what it owns by kind and the last 30 days of routed
 * findings. A mocked `fetch` answers the `/api/teams` BFF routes the way apiome-rest does.
 *
 * Pinned:
 * - the open-findings figure is exactly the activity read's `open_findings` — apiome-rest counts the
 *   reader's unread owner-finding rows for the team, the same rows the bell counts;
 * - owned entities group by kind and link to their pages; a consumer, which has no page, does not;
 * - a routed finding's link is followed only when it is an app path;
 * - both pages render without axe violations, and dump the docs fixtures `teams` and `team-detail`.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
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

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'user-1', name: 'Ada', email: 'ada@example.com', current_tenant_id: 'tenant-1' } },
  }),
}));

import TeamsClient from '../src/app/ade/dashboard/teams/TeamsClient';
import TeamDetailClient from '../src/app/ade/dashboard/teams/[slug]/TeamDetailClient';
import type { Team, TeamActivity } from '../lib/owners';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const PAYMENTS: Team = {
  id: 't-1',
  slug: 'payments',
  name: 'Payments',
  description: 'Card rails, refunds and the ledger.',
  contact_email: 'payments@example.com',
  chat_url: 'https://chat.example.com/c/payments',
  oncall_url: 'https://oncall.example.com/payments',
  docs_url: null,
  member_count: 3,
  members: [
    { user_id: 'u-1', role: 'lead', name: 'Priya Raman', email: 'priya@example.com' },
    { user_id: 'u-2', role: 'member', name: 'Marcus Lee', email: 'marcus@example.com' },
    { user_id: 'u-3', role: 'member', name: null, email: 'sam@example.com' },
  ],
};

const PLATFORM: Team = {
  id: 't-2',
  slug: 'platform',
  name: 'Platform',
  member_count: 5,
  chat_url: 'https://chat.example.com/c/platform',
};

const ACTIVITY: TeamActivity = {
  team_id: 't-1',
  owned: [
    { kind: 'project', id: 'p-1', name: 'Payments API', source: 'manual' },
    { kind: 'catalog_item', id: 'c-1', name: 'Ledger events', source: 'gateway_tag' },
    { kind: 'catalog_item', id: 'c-2', name: 'Refunds gRPC', source: 'codeowners' },
    { kind: 'consumer', id: 'k-1', name: 'Checkout', source: 'manual' },
    { kind: 'connector', id: 'n-1', name: 'Prod Kong', source: 'manual' },
  ],
  owned_counts: { project: 1, catalog_item: 2, consumer: 1, connector: 1 },
  suggested_count: 2,
  open_findings: 3,
  events: [
    {
      type: 'owner_breaking_change',
      entity_kind: 'project',
      entity_id: 'p-1',
      entity_name: 'Payments API',
      summary: 'A refresh of acme/payments introduced 2 breaking changes',
      link: '/ade/dashboard/versions?projectId=p-1',
      created_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
      recipients: 3,
    },
    {
      type: 'owner_sync_failed',
      entity_kind: 'connector',
      entity_id: 'n-1',
      entity_name: 'Prod Kong',
      summary: 'Prod Kong failed to sync (auth)',
      link: 'https://evil.example/phish',
      created_at: new Date(Date.now() - 26 * 3600_000).toISOString(),
      recipients: 3,
    },
  ],
};

let teamsResponse: { ok: boolean; body: unknown } = { ok: true, body: { teams: [PAYMENTS, PLATFORM], count: 2 } };

beforeEach(() => {
  teamsResponse = { ok: true, body: { teams: [PAYMENTS, PLATFORM], count: 2 } };
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const reply = (ok: boolean, body: unknown) =>
      ({ ok, status: ok ? 200 : 500, json: async () => body }) as Response;
    if (url === '/api/teams') return reply(teamsResponse.ok, teamsResponse.body);
    if (url === '/api/teams/payments') return reply(true, PAYMENTS);
    if (url === '/api/teams/payments/activity') return reply(true, ACTIVITY);
    return reply(false, { error: 'not found' });
  }) as unknown as typeof fetch;
});

describe('the teams list', () => {
  test('lists every team with its members and links, each linking to its page', async () => {
    const { container } = render(<TeamsClient />);
    const row = await screen.findByTestId('team-row-payments');
    expect(within(row).getByRole('link', { name: 'Payments' })).toHaveAttribute('href', '/ade/dashboard/teams/payments');
    expect(row).toHaveTextContent('3');
    expect(within(row).getByRole('link', { name: 'Contact' })).toHaveAttribute('href', 'mailto:payments@example.com');
    expect(within(row).getByRole('link', { name: 'Chat' })).toHaveAttribute('href', 'https://chat.example.com/c/payments');
    expect(within(row).getByRole('link', { name: 'On-call' })).toBeInTheDocument();
    expect(within(row).queryByRole('link', { name: 'Docs' })).not.toBeInTheDocument();
    expect(screen.getByTestId('team-row-platform')).toHaveTextContent('5');

    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('teams', (document.querySelector('.page') ?? container.firstElementChild)!.outerHTML);
  });

  test('says how to make the first team when there are none', async () => {
    teamsResponse = { ok: true, body: { teams: [], count: 0 } };
    render(<TeamsClient />);
    expect(await screen.findByText('No teams yet')).toBeInTheDocument();
  });

  test('reports a failed read instead of drawing an empty list', async () => {
    teamsResponse = { ok: false, body: { error: 'Permission denied: teams:view is required' } };
    render(<TeamsClient />);
    expect(await screen.findByText('The teams could not be read')).toBeInTheDocument();
    expect(screen.getByText('Permission denied: teams:view is required')).toBeInTheDocument();
  });
});

describe('a team page', () => {
  test('counts the reader’s open findings exactly as the activity read reports them', async () => {
    render(<TeamDetailClient slug="payments" />);
    const open = await screen.findByTestId('team-open-findings');
    expect(open).toHaveTextContent('3');
    expect(open).toHaveTextContent('Open findings for you');
    expect(open).toHaveAttribute('href', '/ade/dashboard/notifications');
  });

  test('lists members leads first, and what the team owns grouped by kind', async () => {
    render(<TeamDetailClient slug="payments" />);
    const members = await screen.findByTestId('team-members');
    const names = within(members).getAllByRole('listitem').map((item) => item.textContent);
    expect(names[0]).toContain('Priya Raman');
    expect(names[0]).toContain('Lead');
    expect(names[2]).toContain('sam@example.com');

    const owned = screen.getByTestId('team-owned');
    expect(within(owned).getByRole('heading', { name: /Catalog items/ })).toHaveTextContent('2');
    expect(within(owned).getByRole('link', { name: 'Ledger events' })).toHaveAttribute('href', '/ade/dashboard/catalog/c-1');
    expect(within(owned).getByRole('link', { name: 'Payments API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=p-1'
    );
    // A consumer has no page of its own, so it is named but not linked.
    expect(within(owned).getByText('Checkout').tagName).toBe('SPAN');
    expect(within(owned).getByText('CODEOWNERS')).toBeInTheDocument();
  });

  test('lists routed findings, linking only to app paths', async () => {
    const { container } = render(<TeamDetailClient slug="payments" />);
    const events = await screen.findByTestId('team-events');
    expect(
      within(events).getByRole('link', { name: 'A refresh of acme/payments introduced 2 breaking changes' })
    ).toHaveAttribute('href', '/ade/dashboard/versions?projectId=p-1');
    expect(within(events).queryByRole('link', { name: 'Prod Kong failed to sync (auth)' })).not.toBeInTheDocument();
    expect(within(events).getByText('Breaking changes')).toBeInTheDocument();
    expect(within(events).getByText('Failed connector syncs')).toBeInTheDocument();

    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('team-detail', (document.querySelector('.page') ?? container.firstElementChild)!.outerHTML);
  });

  test('reports a team that cannot be read', async () => {
    render(<TeamDetailClient slug="ghost" />);
    await waitFor(() => expect(screen.getByText('The team could not be read')).toBeInTheDocument());
  });
});
